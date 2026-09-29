"""DELETE /internal/users/{id} — hesap silindiginde profili, olcumleri ve kalibrasyonu temizler.
Gateway bu yolu yayinlamaz; yalnizca compose agi icinden cagrilir."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, Field

from app import push
from app.config import settings
from app.errors import ApiError, forbidden
from app.repo import devices, processed_events, referrals, users
from app.worker import referral_consumer

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
    """Kullanıcının profilini, ölçümlerini ve kalibrasyonlarını siler."""
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

    # ★ SIRA: ÖNCE SİL, SONRA İŞARETLE ★ Firestore'da özyinelemeli silme bir
    # transaction'a girmiyor. Silme kendi başına idempotent (olmayanı silmek
    # zararsız), bu yüzden önce silinip sonra event işlendi sayılıyor: arada
    # çökülürse yeniden teslimde tekrar silinir, veri kalmaz. Ters sıra (önce
    # işaretle) çökmede veriyi SONSUZA kadar bırakırdı.
    if await processed_events.exists(event_id):
        logger.info("event zaten işlenmiş, atlanıyor event_id=%s", event_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    deleted = await users.delete_all(user_id)
    await referrals.delete_for(user_id)
    await devices.delete_for(user_id)
    await processed_events.claim(event_id, EVENT_ACCOUNT_DELETED)

    logger.info(
        "hesap silme işlendi user_id=%s silinen_doküman=%s", user_id, deleted,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
async def receive_event(envelope: dict, x_internal_key: str | None = Header(default=None)) -> Response:
    """Outbox olayının HTTP ile teslimi (ADR 0020) — davet ödülü tüketicisi."""
    _require_internal_key(x_internal_key)
    await referral_consumer.handle(envelope)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PushIn(BaseModel):
    user_id: uuid.UUID
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(max_length=500)
    channel: str = Field(default=push.CHANNEL_SOCIAL, pattern="^(messages|social)$")
    data: dict[str, str] = Field(default_factory=dict)


class PushOut(BaseModel):
    sent: int


@router.post("/push", response_model=PushOut)
async def send_push(body: PushIn, x_internal_key: str | None = Header(default=None)) -> PushOut:
    """Başka bir servisin (chat, social) kullanıcıya bildirim isteği.

    Kayıtlı cihaz yoksa 0 döner — hata değil (bildirim izni verilmemiş olabilir).
    """
    _require_internal_key(x_internal_key)
    tokens = await devices.tokens_for(body.user_id)
    if not tokens:
        return PushOut(sent=0)
    result = await push.send_multicast(tokens, body.title, body.body, body.data, body.channel)
    if result.invalid_tokens:
        await devices.remove_tokens(result.invalid_tokens)
        logger.info("geçersiz FCM token silindi adet=%d", len(result.invalid_tokens))
    return PushOut(sent=result.sent)
