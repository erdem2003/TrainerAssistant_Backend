"""social-service'e senkron dahili çağrılar (Faz S6).

TEK SENKRON ÇAĞRI NOKTASI — gerekçe `app/config.py`'deki `social_service_url`
alanında. İki fonksiyon da ağın/karşı servisin çökmesine karşı FAIL-CLOSED:
arkadaşlık kontrolü başarısızsa mesaj REDDEDİLİR, profil toplu çekimi
başarısızsa boş sözlük döner ("Bilinmeyen kullanıcı").

★ TAŞIYICI ENJEKTE EDİLEBİLİR (ADR 0019) ★ `use_transport()` ile HTTP yerine
bir ASGI taşıyıcısı verilebilir: tek süreçli dağıtımda social-service aynı
süreçte olduğu için çağrı ağa çıkmadan uygulamaya gider (sözleşme — iç uç,
anahtar, JSON — aynen kalır). Testler de bu yolla gerçek social uygulamasını
bağlıyor.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0)

_transport: httpx.AsyncBaseTransport | None = None
_base_url: str | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None, base_url: str | None = None) -> None:
    """`None` → varsayılan HTTP (`settings.social_service_url`)."""
    global _transport, _base_url
    _transport, _base_url = transport, base_url


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=_TIMEOUT,
        transport=_transport,
        base_url=_base_url or settings.social_service_url,
    )


@dataclass(frozen=True)
class ProfileSummary:
    user_id: str
    username: str
    display_name: str
    avatar_seed: str


async def are_friends(user_a: uuid.UUID, user_b: uuid.UUID) -> bool:
    headers = {"X-Internal-Key": settings.internal_api_key}
    params = {"a": str(user_a), "b": str(user_b)}
    try:
        async with _client() as client:
            response = await client.get("/internal/friendships/check", headers=headers, params=params)
            response.raise_for_status()
            return bool(response.json().get("are_friends", False))
    except httpx.HTTPError:
        logger.exception("social-service arkadaşlık kontrolü başarısız a=%s b=%s", user_a, user_b)
        return False


async def fetch_profiles(user_ids: list[uuid.UUID]) -> dict[str, ProfileSummary]:
    if not user_ids:
        return {}
    headers = {"X-Internal-Key": settings.internal_api_key}
    params = {"ids": ",".join(str(u) for u in user_ids)}
    try:
        async with _client() as client:
            response = await client.get("/internal/profiles/batch", headers=headers, params=params)
            response.raise_for_status()
            items = response.json().get("items", [])
            return {item["user_id"]: ProfileSummary(**item) for item in items}
    except httpx.HTTPError:
        logger.exception("social-service profil toplu çekimi başarısız")
        return {}
