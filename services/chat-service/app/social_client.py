"""social-service'e senkron dahili cagrılar (Faz S6).

TEK SENKRON CAGRI NOKTASI — gerekce `app/config.py`'deki `social_service_url`
alaninda. Her iki fonksiyon da agin/karsi servisin cokmesine karsi
FAIL-CLOSED davranir: friendship kontrolu basarisiz olursa mesaj REDDEDILIR
(izin verilmez), profil toplu cekimi basarisiz olursa bos sozluk doner
(cagiran taraf "Bilinmeyen kullanici" gosterir) — ikisi de veri sizdirmaktan
daha guvenli taraf.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0)


@dataclass(frozen=True)
class ProfileSummary:
    user_id: str
    username: str
    display_name: str
    avatar_seed: str


async def are_friends(user_a: uuid.UUID, user_b: uuid.UUID) -> bool:
    url = f"{settings.social_service_url}/internal/friendships/check"
    headers = {"X-Internal-Key": settings.internal_api_key}
    params = {"a": str(user_a), "b": str(user_b)}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return bool(response.json().get("are_friends", False))
    except httpx.HTTPError:
        logger.exception("social-service arkadaşlık kontrolü başarısız a=%s b=%s", user_a, user_b)
        return False


async def fetch_profiles(user_ids: list[uuid.UUID]) -> dict[str, ProfileSummary]:
    if not user_ids:
        return {}

    url = f"{settings.social_service_url}/internal/profiles/batch"
    headers = {"X-Internal-Key": settings.internal_api_key}
    params = {"ids": ",".join(str(u) for u in user_ids)}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            items = response.json().get("items", [])
            return {item["user_id"]: ProfileSummary(**item) for item in items}
    except httpx.HTTPError:
        logger.exception("social-service profil toplu çekimi başarısız")
        return {}
