"""Etkisi başka serviste yaşayan ödüllerin iletimi — `POST {servis}/internal/rewards`.

★ SIRA: ÖNCE İLET, SONRA İŞLENDİ YAZ ★ İletim başarısızsa SSV 500 döner ve AdMob
aynı isteği tekrar gönderir; hedef servis `transaction_id` ile idempotent olduğu
için ikinci gelişte ödül ikinci kez verilmez. Ters sırada (önce kaydet) iletim
hatası ödülü kalıcı olarak kaybettirirdi.

Tek süreçli dağıtımda `use_apps()` ile ağa çıkmadan hedef uygulamaya gider.
"""

from __future__ import annotations

import uuid

import httpx

from app.config import settings

_TIMEOUT = httpx.Timeout(10.0)
_apps: dict[str, object] = {}


def use_apps(apps: dict[str, object]) -> None:
    """Tek süreç: {"social": asgi_app, "workout": asgi_app}."""
    _apps.clear()
    _apps.update(apps)


def _client(service: str) -> httpx.AsyncClient:
    if service in _apps:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=_apps[service]),
                                 base_url=f"http://{service}.internal", timeout=_TIMEOUT)
    url = settings.social_service_url if service == "social" else settings.workout_service_url
    if not url:
        raise RuntimeError(f"{service} servis adresi tanımsız")
    return httpx.AsyncClient(base_url=url, timeout=_TIMEOUT)


async def forward(service: str, user_id: uuid.UUID, reward: str, transaction_id: str) -> None:
    """Hata fırlatır (ağ, 5xx): çağıran SSV'yi 500'le yanıtlar, AdMob yeniden dener."""
    async with _client(service) as client:
        response = await client.post(
            "/internal/rewards",
            json={"user_id": str(user_id), "reward": reward, "transaction_id": transaction_id},
            headers={"X-Internal-Key": settings.internal_api_key},
        )
        response.raise_for_status()
