"""Meydan okuma + kudos (ADR 0014, Faz S9).

TEK DOĞRULUK KAYNAĞI: `app/repo/challenges.py` — ilerlemenin saklanmadığı,
her sorguda `workout_snapshots`'tan hesaplandığı gerekçesi orada.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Response, status

from app import notify
from app.db import db
from app.errors import not_found, unprocessable
from app.identity import require_user_id
from app.repo import challenges, friendships, notifications, posts
from app.schemas import (
    ChallengeIn,
    ChallengeListOut,
    ChallengeOut,
    ChallengeParticipantOut,
    KudosOut,
)

router = APIRouter(prefix="/v1/social", tags=["challenges"])


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise unprocessable(f"{field} geçerli bir UUID değil") from None


def _from_epoch_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


async def _build_challenge_out(conn, challenge: challenges.Challenge, viewer_id: uuid.UUID) -> ChallengeOut:
    participant_rows = await challenges.list_participants(conn, challenge.id)
    user_ids = [r["user_id"] for r in participant_rows]
    progress = await challenges.fetch_progress(
        conn, user_ids, challenge.starts_at, challenge.ends_at, challenge.exercise_id
    )
    return ChallengeOut(
        id=str(challenge.id),
        creator_id=str(challenge.creator_id),
        title=challenge.title,
        exercise_id=challenge.exercise_id,
        target_reps=challenge.target_reps,
        starts_at=_epoch_ms(challenge.starts_at),
        ends_at=_epoch_ms(challenge.ends_at),
        participants=[
            ChallengeParticipantOut(
                user_id=str(r["user_id"]),
                username=r["username"],
                display_name=r["display_name"],
                avatar_seed=r["avatar_seed"],
                progress_reps=progress.get(r["user_id"], 0),
                is_me=(r["user_id"] == viewer_id),
            )
            for r in participant_rows
        ],
    )


@router.post("/challenges", response_model=ChallengeOut, status_code=status.HTTP_201_CREATED)
async def create_challenge(
    body: ChallengeIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> ChallengeOut:
    creator_id = require_user_id(x_user_id)
    challenge_id = _parse_uuid(body.id, "id")
    starts_at = _from_epoch_ms(body.starts_at)
    ends_at = _from_epoch_ms(body.ends_at)

    if ends_at <= starts_at:
        raise unprocessable("ends_at, starts_at'ten sonra olmalı")

    async with db.pool.acquire() as conn:
        existing = await challenges.find_by_id(conn, challenge_id)
        if existing is not None:
            if existing.creator_id != creator_id:
                raise not_found("Meydan okuma bulunamadı")
            response.status_code = status.HTTP_200_OK
            return await _build_challenge_out(conn, existing, creator_id)

        await challenges.create(
            conn,
            challenge_id=challenge_id,
            creator_id=creator_id,
            title=body.title,
            exercise_id=body.exercise_id,
            target_reps=body.target_reps,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        created = await challenges.find_by_id(conn, challenge_id)
        assert created is not None
        return await _build_challenge_out(conn, created, creator_id)


@router.get("/challenges", response_model=ChallengeListOut)
async def list_challenges(x_user_id: str | None = Header(default=None)) -> ChallengeListOut:
    viewer_id = require_user_id(x_user_id)

    async with db.pool.acquire() as conn:
        rows = await challenges.list_for_user(conn, viewer_id)
        items = [await _build_challenge_out(conn, c, viewer_id) for c in rows]

    return ChallengeListOut(items=items)


@router.post("/challenges/{challenge_id}/join", response_model=ChallengeOut)
async def join_challenge(
    challenge_id: str,
    x_user_id: str | None = Header(default=None),
) -> ChallengeOut:
    """Yalnızca kurucunun ARKADAŞI katılabilir — meydan okuma da gönderi/feed
    gibi arkadaş çevresiyle sınırlı bir sosyal nesne (ADR 0014 karar #3)."""
    viewer_id = require_user_id(x_user_id)
    cid = _parse_uuid(challenge_id, "challenge_id")

    async with db.pool.acquire() as conn:
        challenge = await challenges.find_by_id(conn, cid)
        if challenge is None:
            raise not_found("Meydan okuma bulunamadı")

        if challenge.creator_id != viewer_id and not await friendships.are_friends(
            conn, viewer_id, challenge.creator_id
        ):
            raise not_found("Meydan okuma bulunamadı")

        await challenges.join(conn, cid, viewer_id)
        return await _build_challenge_out(conn, challenge, viewer_id)


# --- Kudos ---------------------------------------------------------------------


@router.post("/workouts/{workout_id}/kudos", response_model=KudosOut)
async def give_kudos(workout_id: str, x_user_id: str | None = Header(default=None)) -> KudosOut:
    giver_id = require_user_id(x_user_id)
    wid = _parse_uuid(workout_id, "workout_id")

    upserted_notification = None
    async with db.pool.acquire() as conn:
        owner_id = await posts.find_snapshot_owner(conn, wid)
        if owner_id is None:
            raise not_found("Antrenman bulunamadı")

        if owner_id != giver_id and not await friendships.are_friends(conn, giver_id, owner_id):
            raise not_found("Antrenman bulunamadı")

        is_new = await challenges.give_kudos(conn, wid, giver_id)
        count = await challenges.count_kudos(conn, wid)

        if is_new and owner_id != giver_id:
            upserted_notification = await notifications.upsert(
                conn,
                notification_id=uuid.uuid4(),
                recipient_id=owner_id,
                notification_type="WORKOUT_KUDOS",
                actor_id=giver_id,
                subject_id=wid,
            )

    if upserted_notification is not None:
        await notify.publish_notification(
            owner_id,
            notification_id=upserted_notification.id,
            notification_type="WORKOUT_KUDOS",
            actor_id=giver_id,
            subject_id=wid,
            created_at_ms=int(upserted_notification.created_at.timestamp() * 1000),
        )

    return KudosOut(workout_id=str(wid), kudos_count=count, given_by_me=True)


@router.delete("/workouts/{workout_id}/kudos", response_model=KudosOut)
async def remove_kudos(workout_id: str, x_user_id: str | None = Header(default=None)) -> KudosOut:
    giver_id = require_user_id(x_user_id)
    wid = _parse_uuid(workout_id, "workout_id")

    async with db.pool.acquire() as conn:
        await challenges.remove_kudos(conn, wid, giver_id)
        count = await challenges.count_kudos(conn, wid)

    return KudosOut(workout_id=str(wid), kudos_count=count, given_by_me=False)
