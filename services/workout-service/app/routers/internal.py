"""DELETE /internal/users/{id} — hesap silindiginde antrenmanlari temizler.
Gateway bu yolu yayinlamaz; yalnizca compose agi icinden cagrilir."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Response, status

from app.config import settings
from app.db import db
from app.errors import ApiError, forbidden
from app.repo import plan, processed_events, workouts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

EVENT_ACCOUNT_DELETED = "AccountDeleted"


def _require_internal_key(provided: str | None) -> None:
    if not settings.internal_api_key:
        # Sır tanımlanmamışsa uç KAPALI. Açık bırakmak, yapılandırma eksikliğini
        # sessizce bir güvenlik açığına çevirirdi.
        logger.error("INTERNAL_API_KEY tanımsız — /internal uçları kapalı")
        raise forbidden()
    if provided != settings.internal_api_key:
        logger.warning("geçersiz internal anahtarı ile /internal çağrısı")
        raise forbidden()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_data(
    user_id: uuid.UUID,
    x_internal_key: str | None = Header(default=None),
    x_event_id: str | None = Header(default=None),
) -> Response:
    """Kullanıcının tüm antrenmanlarını siler (sets/reps CASCADE ile gider)."""
    _require_internal_key(x_internal_key)

    if not x_event_id:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "X-Event-Id başlığı zorunlu",
        )

    try:
        event_id = uuid.UUID(x_event_id)
    except ValueError:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "X-Event-Id geçerli bir UUID olmalı",
        ) from None

    async with db.pool.acquire() as conn:
        # Idempotency kaydı ve silme AYNI TRANSACTION'da. Ayrı olsalardı, kayıt
        # yazılıp silme başarısız olduğunda event "işlendi" sayılır ve profil
        # sonsuza kadar kalırdı.
        async with conn.transaction():
            first_time = await processed_events.claim(
                conn, event_id, EVENT_ACCOUNT_DELETED
            )
            if not first_time:
                logger.info("event zaten işlenmiş, atlanıyor event_id=%s", event_id)
                return Response(status_code=status.HTTP_204_NO_CONTENT)

            deleted = await workouts.delete_by_user(conn, user_id)
            # Program kalemleri CASCADE ile GİTMEZ: `plan_items` antrenmana
            # değil kullanıcıya bağlı (user_id kolonu, foreign key yok — ADR
            # 0005). Ayrıca silinmesi gerekiyor, yoksa hesap silindikten sonra
            # kullanıcının programı veritabanında kalırdı.
            deleted_plan = await plan.delete_by_user(conn, user_id)

    logger.info(
        "hesap silme işlendi user_id=%s silinen_antrenman=%s silinen_plan=%s",
        user_id, deleted, deleted_plan,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
