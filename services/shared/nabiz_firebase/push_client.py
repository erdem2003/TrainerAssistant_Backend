"""Başka servisten push bildirimi isteği — user-service `POST /internal/push`.

Cihaz token'ları user-service'te (database-per-service); chat ve social
bildirimi bu istemciyle ister.

★ BAŞARISIZLIK YUTULUR ★ Bildirim yan etki: gönderilemezse mesaj/beğeni yine
kaydedilmiş olmalı. Hata yalnız loglanır.

★ NEDEN YANITTAN ÖNCE, BEKLENEREK ★ Cloud Run yanıt gönderildikten sonra
CPU'yu kısıyor; arka plana bırakılan istek dakikalarca gecikebilir ya da hiç
gitmez. Bu yüzden çağrı isteğin içinde, kısa bir zaman aşımıyla bekleniyor.

`USER_SERVICE_URL` tanımsızsa (yerel geliştirme, testler) hiçbir şey yapmaz.
Tek süreçli dağıtımda `use_transport()` ile ağa çıkmadan user uygulamasına gider.
"""

from __future__ import annotations

import logging
import os
import uuid

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(6.0)

_transport: httpx.AsyncBaseTransport | None = None
_base_url: str | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None, base_url: str | None = None) -> None:
    global _transport, _base_url
    _transport, _base_url = transport, base_url


async def notify(
    user_id: uuid.UUID | str,
    title: str,
    body: str,
    *,
    channel: str = "social",
    data: dict[str, str] | None = None,
) -> None:
    base_url = _base_url or os.environ.get("USER_SERVICE_URL")
    if not base_url:
        return
    payload = {
        "user_id": str(user_id),
        "title": title[:120],
        "body": body[:500],
        "channel": channel,
        "data": data or {},
    }
    headers = {"X-Internal-Key": os.environ.get("INTERNAL_API_KEY", "")}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=_transport, base_url=base_url) as client:
            response = await client.post("/internal/push", json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("push isteği başarısız user_id=%s", user_id, exc_info=True)
