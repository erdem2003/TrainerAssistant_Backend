"""Süreç içi hız sınırlama (ADR 0014 Faz S10; ADR 0019 karar 6).

Redis kalktı: dağıtım tek süreç (ADR 0019 karar 1), sayaçların süreç belleğinde
durması DOĞRU sonuç veriyor. Arayüz Redis sürümüyle AYNI (`connect/close/hit`),
router'lar değişmedi. Pencere biçimi de aynı: sabit pencere — ilk vuruşta
başlar, `window_seconds` sonra sıfırlanır (Redis'teki INCR + EXPIRE).

Bilinen bedel: süreç yeniden başlarsa sayaçlar sıfırlanır (Render'ın uyku/
uyanma döngüsü dahil). Kapsam spam sınırı, kimlik doğrulama değil — kabul
edilebilir. Birden çok süreçe geçilirse Render Key Value (Redis) sürümüne
dönülmeli; arayüz aynı olduğu için yalnızca bu dosya değişir.
"""

from __future__ import annotations

import asyncio
import time

from app.errors import rate_limited

# Bellek sızmasın: süresi dolmuş anahtarlar bu kadar vuruşta bir süpürülüyor.
_SWEEP_EVERY = 1000


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = asyncio.Lock()
        self._hits = 0

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        self._windows.clear()

    def reset(self) -> None:
        """Testler için."""
        self._windows.clear()

    async def hit(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        async with self._lock:
            started, count = self._windows.get(key, (now, 0))
            if now - started >= window_seconds:
                started, count = now, 0
            count += 1
            self._windows[key] = (started, count)
            self._hits += 1
            if self._hits % _SWEEP_EVERY == 0:
                self._sweep(now, window_seconds)
        if count > limit:
            raise rate_limited(max(int(window_seconds - (now - started)), 1))

    def _sweep(self, now: float, window_seconds: int) -> None:
        # Pencere uzunlukları anahtara göre değişiyor (10 dk / 1 sa); en uzun
        # pencereden (1 sa) eski olan her anahtar güvenle atılabilir.
        horizon = max(window_seconds, 3600)
        for key in [k for k, (started, _) in self._windows.items() if now - started >= horizon]:
            del self._windows[key]


limiter = RateLimiter()


def post_create_key(user_id: object) -> str:
    return f"rl:post:create:{user_id}"


def comment_create_key(user_id: object) -> str:
    return f"rl:comment:create:{user_id}"


def friend_request_key(user_id: object) -> str:
    return f"rl:friend:request:{user_id}"
