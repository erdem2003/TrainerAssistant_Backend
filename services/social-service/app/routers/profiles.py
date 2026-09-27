"""Sosyal profil: kullanici adi alma, arama, gorunum.

TEK DOGRULUK KAYNAGI: ADR 0014. Kullanici adi `social_db`'de yasiyor,
`user_db`'de degil — gerekce ADR'nin "Kullanıcı adı neden social_db'de"
bolumunde.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query

from app.db import db
from app.errors import conflict, not_found
from app.identity import require_user_id
from app.repo import profiles
from app.schemas import (
    ProfileOut,
    ProfileSearchOut,
    ProfileSummaryOut,
    UsernameClaimIn,
)

router = APIRouter(prefix="/v1/social/profiles", tags=["profiles"])

_SEARCH_LIMIT_DEFAULT = 20
_SEARCH_LIMIT_MAX = 50


@router.post("/username", response_model=ProfileOut)
async def claim_username(
    body: UsernameClaimIn,
    x_user_id: str | None = Header(default=None),
) -> ProfileOut:
    """Sosyali açar: kullanıcı adını alır, `social_enabled=true` yapar.

    409: kullanıcı adı başkasında ya da 30 günlük soğuma listesinde
    (`retired_usernames` — ADR 0014, "kullanıcı adı yeniden alınamaz").
    """
    user_id = require_user_id(x_user_id)

    async with db.pool.acquire() as conn:
        await profiles.ensure_placeholder(conn, user_id, body.username)

        if await profiles.is_username_taken(conn, body.username, user_id):
            raise conflict(
                "Bu kullanıcı adı alınmış",
                {"username": body.username},
            )

        await profiles.claim_username(conn, user_id, body.username, body.display_name)
        profile = await profiles.find_by_user_id(conn, user_id)

    assert profile is not None
    return ProfileOut(
        user_id=str(profile.user_id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_seed=profile.avatar_seed,
        social_enabled=profile.social_enabled,
    )


@router.get("/me", response_model=ProfileOut)
async def my_profile(x_user_id: str | None = Header(default=None)) -> ProfileOut:
    user_id = require_user_id(x_user_id)

    async with db.pool.acquire() as conn:
        profile = await profiles.find_by_user_id(conn, user_id)

    if profile is None:
        return ProfileOut(
            user_id=str(user_id),
            username="",
            display_name="",
            avatar_seed=str(user_id),
            social_enabled=False,
        )

    return ProfileOut(
        user_id=str(profile.user_id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_seed=profile.avatar_seed,
        social_enabled=profile.social_enabled,
    )


@router.get("/search", response_model=ProfileSearchOut)
async def search_profiles(
    q: str = Query(min_length=1, max_length=24),
    limit: int = Query(default=_SEARCH_LIMIT_DEFAULT, le=_SEARCH_LIMIT_MAX),
    x_user_id: str | None = Header(default=None),
) -> ProfileSearchOut:
    """Yalnızca `social_enabled=true` profiller döner (opt-in, ADR 0014 karar #1),
    kendisi hariç (ADR 0017 — `_SEARCH` artık `viewer_id`'yi dışlıyor).

    Dönen alanlar bilerek dar: yalnızca ad + avatar (ADR 0014 karar #3) —
    arama sonucu arkadaş olmayan biri hakkında hiçbir performans verisi
    sızdırmamalı. `relationship_status` (ADR 0017) ayrı: bu bir performans
    verisi değil, "Ekle" butonunun doğru durumda görünmesi için gerekli —
    olmadan istemci zaten-arkadaş ya da zaten-PENDING birine tekrar istek
    göndermeyi dener, sunucu sessizce hiçbir şey değiştirmeden 200 döner ve
    kullanıcı "çalışmıyor" sanır.
    """
    viewer_id = require_user_id(x_user_id)

    async with db.pool.acquire() as conn:
        rows = await profiles.search(conn, q, limit, viewer_id)

    def _relationship_status(row) -> str:
        status = row["friendship_status"]
        if status is None:
            return "NONE"
        if status == "ACCEPTED":
            return "FRIENDS"
        if row["friendship_requested_by"] == viewer_id:
            return "PENDING_OUTGOING"
        return "PENDING_INCOMING"

    return ProfileSearchOut(
        items=[
            ProfileSummaryOut(
                user_id=str(r["user_id"]),
                username=r["username"],
                display_name=r["display_name"],
                avatar_seed=r["avatar_seed"],
                relationship_status=_relationship_status(r),
            )
            for r in rows
        ]
    )


@router.get("/{target_user_id}", response_model=ProfileSummaryOut)
async def get_profile(
    target_user_id: str,
    x_user_id: str | None = Header(default=None),
) -> ProfileSummaryOut:
    """Arkadaş olmayan biri için de sınırlı gövde döner — 403 değil.

    404 yalnızca profil hiç yoksa (kullanıcı sosyali hiç açmamış). Var olan
    ama arkadaş olunmayan bir profili gizlemek `service-contract` §3'ün
    "başkasının kaynağı 404" kuralının ötesinde bir durum: burada kaynak
    GERÇEKTEN var, yalnızca görünürlüğü daralıyor — bu yüzden 200 + dar gövde.
    """
    require_user_id(x_user_id)
    try:
        target = uuid.UUID(target_user_id)
    except ValueError:
        raise not_found() from None

    # v1'de arkadaş olsun olmasın dönen alanlar zaten aynı (yalnız ad+avatar,
    # ADR 0014 karar #3) — bu yüzden burada `are_friends` kontrolü YOK. Skor/
    # gönderi gibi genişletilmiş alanlar eklendiğinde (S4/S5) bu uç arkadaş
    # olmayana onları göstermemek için `friendships.are_friends`'i çağıracak.
    async with db.pool.acquire() as conn:
        profile = await profiles.find_by_user_id(conn, target)
        if profile is None or not profile.social_enabled:
            raise not_found("Kullanıcı bulunamadı")

    return ProfileSummaryOut(
        user_id=str(profile.user_id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_seed=profile.avatar_seed,
    )
