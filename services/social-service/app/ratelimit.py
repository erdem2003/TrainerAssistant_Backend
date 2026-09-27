"""Redis tabanlı hız sınırlama (ADR 0014, Faz S10).

`auth-service/app/ratelimit.py` ile AYNI Lua betiği ve desen — servisler kod
paylaşmıyor (ADR 0005). Kapsam: gönderi oluşturma, yorum, arkadaşlık isteği
(plan dosyasının S10 listesi) — spam/kötüye kullanım sınırı, kimlik doğrulama
değil.
"""

from __future__ import annotations

import logging

import redis.asyncio as redis
from redis.commands.core import AsyncScript

from app.config import settings
from app.errors import rate_limited

logger = logging.getLogger(__name__)

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
        self._script: AsyncScript | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(settings.redis_url, decode_responses=True)
        self._script = self._client.register_script(_INCR_WITH_TTL)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def hit(self, key: str, limit: int, window_seconds: int) -> None:
        if self._client is None or self._script is None:
            return
        try:
            current, ttl = await self._script(keys=[key], args=[window_seconds])
        except Exception:
            # Açık kapı: Redis yoksa yazma durmamalı — auth-service'teki
            # aynı gerekçe.
            logger.exception("hız sınırı kontrol edilemedi, istek geçiriliyor")
            return

        if int(current) > limit:
            raise rate_limited(max(int(ttl), 1))


limiter = RateLimiter()


def post_create_key(user_id: object) -> str:
    return f"rl:post:create:{user_id}"


def comment_create_key(user_id: object) -> str:
    return f"rl:comment:create:{user_id}"


def friend_request_key(user_id: object) -> str:
    return f"rl:friend:request:{user_id}"
