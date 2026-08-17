"""GET /health/live ve /health/ready."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.db import db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict:
    """Süreç ayakta mı. BAĞIMLILIK KONTROL ETMEZ."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict:
    """Trafik alabilir mi. Veritabanı kontrol edilir."""
    database_ok = await db.healthy()

    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "down",
    }
