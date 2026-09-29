"""FCM ile push bildirimi gönderimi (firebase-admin `messaging`).

Cihaz token'ları bu serviste (`repo/devices.py`); diğer servisler bildirimi
`POST /internal/push` ile ister. FCM'in "bu token artık yok" dediği kayıtlar
gönderimden hemen sonra silinir.

`send_multicast` testte yerine başka bir fonksiyon konabilsin diye modül
düzeyinde: gerçek FCM emülatörü yok.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Android bildirim kanalları — mobildeki `PushChannels` ile AYNI kimlikler.
CHANNEL_MESSAGES = "messages"
CHANNEL_SOCIAL = "social"


@dataclass(frozen=True)
class PushResult:
    sent: int
    invalid_tokens: list[str]


def _send_blocking(tokens: list[str], title: str, body: str, data: dict[str, str], channel: str) -> PushResult:
    from firebase_admin import messaging  # noqa: PLC0415 — FCM yalnız bu yolda

    from nabiz_firebase.admin import firebase_app  # noqa: PLC0415

    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=data,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(channel_id=channel, tag=data.get("tag")),
        ),
    )
    response = messaging.send_each_for_multicast(message, app=firebase_app())
    invalid = [
        token
        for token, item in zip(tokens, response.responses, strict=True)
        if not item.success
        and isinstance(item.exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError))
    ]
    for item in response.responses:
        if not item.success and item.exception is not None:
            logger.info("FCM gönderimi başarısız: %s", item.exception)
    return PushResult(sent=response.success_count, invalid_tokens=invalid)


async def send_multicast(
    tokens: list[str], title: str, body: str, data: dict[str, str], channel: str
) -> PushResult:
    # firebase-admin senkron (HTTP isteği); olay döngüsünü tıkamasın.
    return await asyncio.to_thread(_send_blocking, tokens, title, body, data, channel)
