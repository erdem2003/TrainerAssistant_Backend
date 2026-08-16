"""GET /health/live ve /health/ready."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.db import db
from app.ratelimit import limiter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict:
    """Süreç ayakta mı. BAĞIMLILIK KONTROL ETMEZ."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict:
    """Trafik alabilir mi. Veritabanı ve Redis kontrol edilir."""
    database_ok = await db.healthy()
    redis_ok = await limiter.healthy()

    # Redis yoksa servis ÇALIŞIR ama hız sınırı uygulanamaz. Bu bilinçli bir
    # taviz (bkz. ratelimit.py) — yine de `ready` bunu bildirir ki operatör
    # görsün.
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if database_ok and redis_ok else "degraded",
        "database": "ok" if database_ok else "down",
        "redis": "ok" if redis_ok else "down",
    }
