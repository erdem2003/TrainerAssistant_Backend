"""Redis tabanli hiz sinirlama."""

from __future__ import annotations

import logging

import redis.asyncio as redis
from redis.commands.core import AsyncScript

from app.config import settings
from app.errors import rate_limited

logger = logging.getLogger(__name__)

# Sayacı artır ve İLK artışta süre ata. Tek turda çalışsın diye Lua:
# INCR + EXPIRE'ı iki ayrı çağrı yapmak, aradaki çökmede süresiz anahtar bırakır.
_INCR_WITH_TTL = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {current, redis.call('TTL', KEYS[1])}
"""


class RateLimiter:
    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        # Tip acikca yaziliyor: `= None` tek basina birakilinca hem mypy hem
        # PyCharm degiskeni `None` sanip `self._script(...)` cagrisini hata
        # olarak isaretliyor.
        self._script: AsyncScript | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(settings.redis_url, decode_responses=True)
        self._script = self._client.register_script(_INCR_WITH_TTL)
        logger.info("redis bağlantısı hazır")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def healthy(self) -> bool:
        try:
            return bool(self._client is not None and await self._client.ping())
        except Exception:
            logger.exception("redis sağlık kontrolü başarısız")
            return False

    async def hit(self, key: str, limit: int, window_seconds: int) -> None:
        """Sayacı artırır; sınır aşıldıysa `ApiError(429)` fırlatır."""
        # Ikisi birlikte kontrol ediliyor: `connect()` cagrilmadiysa ikisi de
        # `None` olur ve hiz siniri sessizce atlanir (bilincli — bkz. modul basi).
        if self._client is None or self._script is None:
            return

        try:
            current, ttl = await self._script(keys=[key], args=[window_seconds])
        except Exception:
            # Açık kapı: Redis yoksa kimlik doğrulama durmamalı.
            logger.exception("hız sınırı kontrol edilemedi, istek geçiriliyor")
            return

        if int(current) > limit:
            raise rate_limited(max(int(ttl), 1))

limiter = RateLimiter()

# --- Anahtar üreticiler ------------------------------------------------------
# E-posta anahtara HAM olarak girmez.


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def login_email_key(email: str) -> str:
    return f"rl:login:email:{_digest(email)}"


def login_ip_key(ip: str) -> str:
    return f"rl:login:ip:{ip}"


def register_email_key(email: str) -> str:
    return f"rl:register:email:{_digest(email)}"


def register_ip_key(ip: str) -> str:
    return f"rl:register:ip:{ip}"


def resend_email_key(email: str) -> str:
    return f"rl:resend:email:{_digest(email)}"
