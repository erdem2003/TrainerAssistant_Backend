"""DELETE /internal/users/{id} — hesap silindiginde sohbet verisini
redakte eder (ADR 0014, Faz S10). Gateway bu yolu yayinlamaz.

`social-service/app/routers/internal.py`'nin deseni: X-Event-Id +
`processed_events` ile idempotent. FARKI: mesaj DOKUMANLARI SİLİNMEZ, `body`
NULL'lanıp `redacted_at` damgalanır (ADR 0014 Sonuclar, "silme yerine
redaksiyon") — karsi tarafin sohbet gecmisi kirilmadan okunabilir kalir.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Response, status

from app.config import settings
from app.errors import ApiError, forbidden
from app.repo import conversations, messages, processed_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

EVENT_ACCOUNT_DELETED = "AccountDeleted"


def _require_internal_key(provided: str | None) -> None:
    if not settings.internal_api_key:
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
    _require_internal_key(x_internal_key)

    if not x_event_id:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "X-Event-Id başlığı zorunlu"
        )
    try:
        event_id = uuid.UUID(x_event_id)
    except ValueError:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "X-Event-Id geçerli bir UUID olmalı"
        ) from None

    # ★ SIRA: ÖNCE REDAKTE ET, SONRA İŞARETLE ★ (health-service deseni) —
    # redaksiyon idempotent (zaten redakte olan atlanıyor); arada çökülürse
    # yeniden teslimde kalanlar redakte edilir.
    if await processed_events.exists(event_id):
        logger.info("event zaten işlenmiş, atlanıyor event_id=%s", event_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    redacted = await messages.redact_by_sender(user_id)
    for conv_snap in await conversations.for_user(user_id):
        await conversations.mark_left(uuid.UUID(conv_snap.id), user_id)

    await processed_events.claim(event_id, EVENT_ACCOUNT_DELETED)

    logger.info("hesap silme işlendi user_id=%s redakte_edilen_mesaj=%s", user_id, redacted)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
