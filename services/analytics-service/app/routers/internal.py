"""DELETE /internal/users/{id} — hesap silindiginde workout_facts'i temizler.
Gateway bu yolu yayinlamaz; yalnizca compose agi icinden cagrilir.

`workout-service/app/routers/internal.py`'nin BIREBIR deseni — ikinci bir
implementasyon yazmak yerine ayni sekli tekrarlamak, ADR 0005'in "her servis
kendi sinkini uygular" beklentisini karsiliyor.

★ BU DOSYA ONCEDEN YOKTU — SESSIZCE DUSMUS BIR HATA ★
`app/repo/facts.py:delete_by_user` egitilmis, ama HICBIR CAGRAN YOKTU: hesap
silindiginde `auth-service/app/worker/fanout.py` hedef listesinde
analytics-service hic gecmiyordu. Sonuc: bir kullanici hesabini silse bile
`workout_facts`'teki her tekrar, her zaman damgasi SONSUZA KADAR kaliyordu.
Bu dosya ve fanout.py'ye eklenen dorduncu hedef bu acigi kapatiyor.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Response, status

from app.config import settings
from app.db import db
from app.errors import ApiError, forbidden
from app.repo import facts, processed_events

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
    """Kullanıcının tüm workout_facts satırlarını siler."""
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
        # Idempotency kaydı ve silme AYNI TRANSACTION'da — workout-service'teki
        # aynı gerekçe: ayrı olsalardı, kayıt yazılıp silme başarısız olduğunda
        # event "işlendi" sayılır ve satırlar sonsuza kadar kalırdı.
        async with conn.transaction():
            first_time = await processed_events.claim(
                conn, event_id, EVENT_ACCOUNT_DELETED
            )
            if not first_time:
                logger.info("event zaten işlenmiş, atlanıyor event_id=%s", event_id)
                return Response(status_code=status.HTTP_204_NO_CONTENT)

            deleted = await facts.delete_by_user(conn, user_id)

    logger.info(
        "hesap silme işlendi user_id=%s silinen_kayit=%s", user_id, deleted
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
