"""Arkadaslik: istek gonder/kabul et/reddet, liste, kaldir.

TEK DOGRULUK KAYNAGI: `app/repo/friendships.py` — kanonik cift tasarimi ve
otomatik-kabul mantiginin gerekcesi orada.

Bildirim dokumani yaziminin kendisi gercek zamanli sinyal (ADR 0019 karar 5):
mobil `social_users/{uid}/notifications`'i dinliyor; Redis uyandirma cagrisi
(`app/notify.py`) kalkti.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header

from app.errors import not_found, unprocessable
from app.identity import require_user_id
from app.ratelimit import friend_request_key, limiter
from app.repo import friendships, notifications, profiles
from app.schemas import (
    FriendListOut,
    FriendOut,
    FriendRequestIn,
    FriendshipStatusOut,
    PendingRequestOut,
    PendingRequestsOut,
)

router = APIRouter(prefix="/v1/social/friendships", tags=["friendships"])


def _epoch_ms(dt) -> int:
    return int(dt.timestamp() * 1000)


@router.get("", response_model=FriendListOut)
async def list_friends(x_user_id: str | None = Header(default=None)) -> FriendListOut:
    user_id = require_user_id(x_user_id)

    rows = await friendships.list_friends(user_id)
    by_id = await profiles.profiles_map(row["friend_id"] for row in rows)
    items = []
    for row in rows:
        profile = by_id.get(row["friend_id"])
        if profile is None:
            # Profil silinmiş (hesap silme fanout'u henüz işlenmemiş olabilir)
            # — bu satırı atla, çökme yerine.
            continue
        items.append(
            FriendOut(
                user_id=str(profile.user_id),
                username=profile.username,
                display_name=profile.display_name,
                avatar_seed=profile.avatar_seed,
                since=_epoch_ms(row["created_at"]),
            )
        )

    return FriendListOut(items=items)


@router.get("/requests", response_model=PendingRequestsOut)
async def list_requests(x_user_id: str | None = Header(default=None)) -> PendingRequestsOut:
    user_id = require_user_id(x_user_id)

    incoming_rows, outgoing_rows = await friendships.list_pending(user_id)
    by_id = await profiles.profiles_map(
        [r["requester_id"] for r in incoming_rows] + [r["addressee_id"] for r in outgoing_rows]
    )

    def _build(rows: list[dict], key: str) -> list[PendingRequestOut]:
        out = []
        for row in rows:
            profile = by_id.get(row[key])
            if profile is None:
                continue
            out.append(
                PendingRequestOut(
                    user_id=str(profile.user_id),
                    username=profile.username,
                    display_name=profile.display_name,
                    avatar_seed=profile.avatar_seed,
                    requested_at=_epoch_ms(row["created_at"]),
                )
            )
        return out

    return PendingRequestsOut(
        incoming=_build(incoming_rows, "requester_id"),
        outgoing=_build(outgoing_rows, "addressee_id"),
    )


@router.post("", response_model=FriendshipStatusOut)
async def send_request(
    body: FriendRequestIn,
    x_user_id: str | None = Header(default=None),
) -> FriendshipStatusOut:
    me = require_user_id(x_user_id)
    # 20 istek / 10 dakika — art arda spam istek atmayı engeller, normal
    # kullanım (birkaç arkadaş eklemek) hiç yaklaşmayacağı bir sınır.
    await limiter.hit(friend_request_key(me), limit=20, window_seconds=600)

    try:
        target = uuid.UUID(body.user_id)
    except ValueError:
        raise unprocessable("user_id geçerli bir UUID olmalı") from None

    if target == me:
        raise unprocessable("kendine arkadaşlık isteği gönderemezsin")

    target_profile = await profiles.find_by_user_id(target)
    if target_profile is None or not target_profile.social_enabled:
        raise not_found("Kullanıcı bulunamadı")

    result = await friendships.send_request(me, target)

    # ★ HANGİ TARAF NE GÖRÜR ★ PENDING: karşı taraf yeni bir istek aldı.
    # ACCEPTED (karşılıklı istek): karşı taraf zaten bekliyordu, benim
    # isteğim onunkini KABUL etti — bu durumda FRIEND_ACCEPTED gönderiliyor.
    notif_type = "FRIEND_REQUEST" if result.status == "PENDING" else "FRIEND_ACCEPTED"
    await notifications.upsert(
        recipient_id=target,
        notification_type=notif_type,
        actor_id=me,
        subject_id=me,
    )

    return FriendshipStatusOut(status=result.status)


@router.post("/{requester_id}/accept", status_code=204)
async def accept_request(
    requester_id: str,
    x_user_id: str | None = Header(default=None),
) -> None:
    me = require_user_id(x_user_id)
    try:
        requester = uuid.UUID(requester_id)
    except ValueError:
        raise not_found() from None

    if not await friendships.accept(me, requester):
        raise not_found("Bekleyen istek bulunamadı")

    await notifications.upsert(
        recipient_id=requester,
        notification_type="FRIEND_ACCEPTED",
        actor_id=me,
        subject_id=me,
    )


@router.post("/{requester_id}/reject", status_code=204)
async def reject_request(
    requester_id: str,
    x_user_id: str | None = Header(default=None),
) -> None:
    me = require_user_id(x_user_id)
    try:
        requester = uuid.UUID(requester_id)
    except ValueError:
        raise not_found() from None

    await friendships.reject_or_unfriend(me, requester)


@router.delete("/{friend_id}", status_code=204)
async def remove_friend(
    friend_id: str,
    x_user_id: str | None = Header(default=None),
) -> None:
    me = require_user_id(x_user_id)
    try:
        friend = uuid.UUID(friend_id)
    except ValueError:
        raise not_found() from None

    await friendships.reject_or_unfriend(me, friend)
