"""Redis pub/sub üzerinden `chat-service`'e bildirim uyandırma sinyali
(ADR 0014, "Redis pub/sub" bölümü — Faz S8).

`chat-service/app/hub.py` ile AYNI kanal biçimi (`ws:user:{id}`) — iki servis
kod paylaşmıyor (ADR 0005), ama protokol (kanal adı + JSON çerçeve biçimi)
üzerinde anlaşmalı. Bu dosya o sözleşmenin sosyal-servis tarafı.
"""

from __future__ import annotations

import json
import logging
import uuid

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "ws:user:"

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url)
    return _redis


async def close() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


async def publish_notification(
    recipient_id: uuid.UUID,
    *,
    notification_id: uuid.UUID,
    notification_type: str,
    actor_id: uuid.UUID,
    subject_id: uuid.UUID,
    created_at_ms: int,
) -> None:
    frame = {
        "type": "NOTIFICATION",
        "id": str(notification_id),
        "notification_type": notification_type,
        "actor_id": str(actor_id),
        "subject_id": str(subject_id),
        "created_at": created_at_ms,
    }
    try:
        await _client().publish(f"{_CHANNEL_PREFIX}{recipient_id}", json.dumps(frame))
    except Exception:
        # Uyandırma sinyali kaybolsa da bildirim SATIRI zaten yazıldı
        # (transaction bu çağrıdan önce commit edildi) — kullanıcı bir
        # sonraki `GET /v1/social/notifications` çağrısında görür, yalnızca
        # anlık iletim kaçmış olur. Bu yüzden hata burada YUTULUYOR, isteğin
        # tamamı 500 dönmemeli.
        logger.exception("bildirim uyandırma sinyali gönderilemedi recipient_id=%s", recipient_id)
