"""Hesap silme olayını diğer servislere yansıtır (ADR 0019: istek içinde, senkron).

★ TAŞIYICI ENJEKTE EDİLEBİLİR ★ `use_apps()` ile servis başına bir ASGI
uygulaması verilirse çağrı ağa çıkmadan o uygulamaya gider — tek süreçli
dağıtımda (`gateway/main.py`) bütün servisler aynı süreçte. Verilmezse
`settings.<servis>_service_url` üzerinden HTTP (ayrı konteyner düzeni).
Sözleşme iki yolda da aynı: `DELETE /internal/users/{id}` + `X-Internal-Key`
+ `X-Event-Id`.
"""

from __future__ import annotations

import logging

import httpx

from app import events
from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)

_apps: dict[str, object] = {}


class FanoutFailed(Exception):
    """Karşı servis ulaşılamadı ya da hata döndü — silme yeniden denenmeli."""


def use_apps(apps: dict[str, object]) -> None:
    """`{"user-service": asgi_app, ...}` — boş sözlük HTTP'ye döner."""
    _apps.clear()
    _apps.update(apps)


def _client(service: str, base_url: str) -> httpx.AsyncClient:
    app = _apps.get(service)
    if app is not None:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=_TIMEOUT)
    return httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT)


async def _delete_user_data(service: str, base_url: str, event_id: str, user_id: str) -> None:
    """Bir servise kullanıcı verisi silme çağrısı.

    `X-Event-Id` tekrar koruma anahtarı olarak gidiyor: aynı olay yeniden
    teslim edilirse karşı taraf işi atlar ama yine başarı döner.
    """
    headers = {"X-Internal-Key": settings.internal_api_key, "X-Event-Id": event_id}
    try:
        async with _client(service, base_url) as client:
            response = await client.delete(f"/internal/users/{user_id}", headers=headers)
    except httpx.HTTPError as exc:
        raise FanoutFailed(f"{service}'e ulaşılamadı: {exc}") from exc
    if response.status_code not in (200, 204):
        raise FanoutFailed(f"{service} {response.status_code} döndü")


async def dispatch(event_id: str, event_type: str, payload: dict) -> None:
    """Event'in diğer servislere yansıtılması. Çoğu event için hiçbir şey yapmaz."""
    if event_type != events.EVENT_ACCOUNT_DELETED:
        return

    user_id = payload.get("user_id")
    if not user_id:
        # Yeniden denemek düzeltmez — bozuk payload.
        logger.error("AccountDeleted payload'ında user_id yok event_id=%s", event_id)
        return

    # SIRA ÖNEMSİZ ama HEPSİ BAŞARILI OLMALI: biri patlarsa istisna yayılır ve
    # istemci tekrar dener; tümü yeniden çağrılır. Tekrar zararsız, çünkü
    # hepsi `processed_events` ile tekrara dayanıklı.
    #
    # Yeni bir servis kullanıcı verisi tutmaya başladığında bu listeye eklenir.
    targets = [
        ("user-service", settings.user_service_url),
        ("workout-service", settings.workout_service_url),
        ("health-service", settings.health_service_url),
        ("analytics-service", settings.analytics_service_url),
        ("social-service", settings.social_service_url),
        ("chat-service", settings.chat_service_url),
    ]

    for service, base_url in targets:
        await _delete_user_data(service, base_url, event_id, user_id)
        logger.info("%s'e silme bildirildi user_id=%s", service, user_id)
