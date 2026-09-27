"""Arkadaslik: istek gonder/kabul et/reddet, liste, kaldir.

TEK DOGRULUK KAYNAGI: `app/repo/friendships.py` — kanonik cift tasarimi ve
otomatik-kabul mantiginin gerekcesi orada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header

from app import notify
from app.db import db
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

    async with db.pool.acquire() as conn:
        rows = await friendships.list_friends(conn, user_id)
        items = []
        for row in rows:
            profile = await profiles.find_by_user_id(conn, row["friend_id"])
            if profile is None:
                # Profil satırı silinmiş (hesap silme fanout'u henüz
                # işlenmemiş olabilir) — bu satırı atla, çökme yerine.
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

    async def _build(rows: list[dict], key: str, conn) -> list[PendingRequestOut]:
        out = []
        for row in rows:
            profile = await profiles.find_by_user_id(conn, row[key])
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

    async with db.pool.acquire() as conn:
        incoming_rows = await friendships.list_pending_incoming(conn, user_id)
        outgoing_rows = await friendships.list_pending_outgoing(conn, user_id)
        incoming = await _build(incoming_rows, "requester_id", conn)
        outgoing = await _build(outgoing_rows, "addressee_id", conn)

    return PendingRequestsOut(incoming=incoming, outgoing=outgoing)


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

    async with db.pool.acquire() as conn:
        target_profile = await profiles.find_by_user_id(conn, target)
        if target_profile is None or not target_profile.social_enabled:
            raise not_found("Kullanıcı bulunamadı")

        result = await friendships.send_request(conn, me, target)

        # ★ HANGİ TARAF NE GÖRÜR ★ PENDING: karşı taraf yeni bir istek aldı.
        # ACCEPTED (karşılıklı istek): karşı taraf zaten bekliyordu, benim
        # isteğim onunkini KABUL etti — bana ayrıca "istek geldi" göstermek
        # yanlış olurdu, o yüzden bu durumda FRIEND_ACCEPTED gönderiliyor.
        notif_type = "FRIEND_REQUEST" if result.status == "PENDING" else "FRIEND_ACCEPTED"
        upserted = await notifications.upsert(
            conn,
            notification_id=uuid.uuid4(),
            recipient_id=target,
            notification_type=notif_type,
            actor_id=me,
            subject_id=me,
        )

    await notify.publish_notification(
        target,
        notification_id=upserted.id,
        notification_type=notif_type,
        actor_id=me,
        subject_id=me,
        created_at_ms=int(upserted.created_at.timestamp() * 1000),
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

    async with db.pool.acquire() as conn:
        accepted = await friendships.accept(conn, me, requester)
        if not accepted:
            raise not_found("Bekleyen istek bulunamadı")

        upserted = await notifications.upsert(
            conn,
            notification_id=uuid.uuid4(),
            recipient_id=requester,
            notification_type="FRIEND_ACCEPTED",
            actor_id=me,
            subject_id=me,
        )

    await notify.publish_notification(
        requester,
        notification_id=upserted.id,
        notification_type="FRIEND_ACCEPTED",
        actor_id=me,
        subject_id=me,
        created_at_ms=int(upserted.created_at.timestamp() * 1000),
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

    async with db.pool.acquire() as conn:
        await friendships.reject_or_unfriend(conn, me, requester)


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

    async with db.pool.acquire() as conn:
        await friendships.reject_or_unfriend(conn, me, friend)
