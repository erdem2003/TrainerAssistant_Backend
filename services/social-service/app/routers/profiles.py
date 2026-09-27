"""Sosyal profil: kullanici adi alma, arama, gorunum.

TEK DOGRULUK KAYNAGI: ADR 0014. Kullanici adi social servisinde yasiyor,
user servisinde degil — gerekce ADR'nin "Kullanıcı adı neden social_db'de"
bolumunde (Firestore'da `social_profiles` + `social_usernames` kilidi).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query

from app.errors import conflict, not_found
from app.identity import require_user_id
from app.repo import friendships, profiles
from app.schemas import (
    ProfileOut,
    ProfileSearchOut,
    ProfileSummaryOut,
    UsernameClaimIn,
)

router = APIRouter(prefix="/v1/social/profiles", tags=["profiles"])

_SEARCH_LIMIT_DEFAULT = 20
_SEARCH_LIMIT_MAX = 50


def _profile_out(profile: profiles.SocialProfile) -> ProfileOut:
    return ProfileOut(
        user_id=str(profile.user_id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_seed=profile.avatar_seed,
        social_enabled=profile.social_enabled,
    )


@router.post("/username", response_model=ProfileOut)
async def claim_username(
    body: UsernameClaimIn,
    x_user_id: str | None = Header(default=None),
) -> ProfileOut:
    """Sosyali açar: kullanıcı adını alır, `social_enabled=true` yapar.

    409: kullanıcı adı başkasında ya da emekli (hesap silmeyle serbest kalmış —
    ADR 0014, "kullanıcı adı yeniden alınamaz"). Kontrol ve alım TEK
    transaction'da: eşzamanlı iki alımdan yalnızca biri kazanır.
    """
    user_id = require_user_id(x_user_id)

    try:
        profile = await profiles.claim_username(user_id, body.username, body.display_name)
    except profiles.UsernameTaken:
        raise conflict("Bu kullanıcı adı alınmış", {"username": body.username}) from None

    return _profile_out(profile)


@router.get("/me", response_model=ProfileOut)
async def my_profile(x_user_id: str | None = Header(default=None)) -> ProfileOut:
    user_id = require_user_id(x_user_id)

    profile = await profiles.find_by_user_id(user_id)

    if profile is None:
        return ProfileOut(
            user_id=str(user_id),
            username="",
            display_name="",
            avatar_seed=str(user_id),
            social_enabled=False,
        )

    return _profile_out(profile)


@router.get("/search", response_model=ProfileSearchOut)
async def search_profiles(
    q: str = Query(min_length=1, max_length=24),
    limit: int = Query(default=_SEARCH_LIMIT_DEFAULT, le=_SEARCH_LIMIT_MAX),
    x_user_id: str | None = Header(default=None),
) -> ProfileSearchOut:
    """Yalnızca `social_enabled=true` profiller döner (opt-in, ADR 0014 karar #1),
    kendisi hariç (ADR 0017).

    Dönen alanlar bilerek dar: yalnızca ad + avatar (ADR 0014 karar #3).
    `relationship_status` (ADR 0017) "Ekle" butonunun doğru durumda görünmesi
    için — olmadan istemci zaten-arkadaş ya da zaten-PENDING birine tekrar
    istek göndermeyi dener ve kullanıcı "çalışmıyor" sanır.
    """
    viewer_id = require_user_id(x_user_id)

    found = await profiles.search(q, limit, viewer_id)
    statuses = await friendships.statuses_with(viewer_id, [p.user_id for p in found])

    def _relationship_status(profile: profiles.SocialProfile) -> str:
        entry = statuses.get(profile.user_id)
        if entry is None:
            return "NONE"
        status, requested_by = entry
        if status == "ACCEPTED":
            return "FRIENDS"
        if requested_by == viewer_id:
            return "PENDING_OUTGOING"
        return "PENDING_INCOMING"

    return ProfileSearchOut(
        items=[
            ProfileSummaryOut(
                user_id=str(p.user_id),
                username=p.username,
                display_name=p.display_name,
                avatar_seed=p.avatar_seed,
                relationship_status=_relationship_status(p),
            )
            for p in found
        ]
    )


@router.get("/{target_user_id}", response_model=ProfileSummaryOut)
async def get_profile(
    target_user_id: str,
    x_user_id: str | None = Header(default=None),
) -> ProfileSummaryOut:
    """Arkadaş olmayan biri için de sınırlı gövde döner — 403 değil.

    404 yalnızca profil hiç yoksa (kullanıcı sosyali hiç açmamış).
    """
    require_user_id(x_user_id)
    try:
        target = uuid.UUID(target_user_id)
    except ValueError:
        raise not_found() from None

    profile = await profiles.find_by_user_id(target)
    if profile is None or not profile.social_enabled:
        raise not_found("Kullanıcı bulunamadı")

    return ProfileSummaryOut(
        user_id=str(profile.user_id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_seed=profile.avatar_seed,
    )
