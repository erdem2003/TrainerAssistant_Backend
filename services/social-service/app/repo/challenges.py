"""Meydan okuma + kudos (ADR 0014, Faz S9).

    social_challenges/{id}                 hedef + `participant_ids` dizisi
    social_kudos/{workout_id}_{giver_id}   (workout_id, giver_id) UNIQUE'in karşılığı

İlerleme burada SAKLANMAZ — her sorguda katılımcıların snapshot'larından
hesaplanır (`fetch_progress`). Katılımcılar ayrı koleksiyon değil dizi: bir
meydan okuma arkadaş çevresiyle sınırlı (onlarca kişi), `array-contains` ile
"katıldığım meydan okumalar" tek alanlı indeksle sorgulanıyor.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from app.db import db
from app.repo import profiles, snapshots


@dataclass(frozen=True)
class Challenge:
    id: uuid.UUID
    creator_id: uuid.UUID
    title: str
    exercise_id: str | None
    target_reps: int
    starts_at: datetime
    ends_at: datetime
    created_at: datetime
    participant_ids: tuple[uuid.UUID, ...] = ()


def _col():
    return db.collection("challenges")


def _kudos():
    return db.collection("kudos")


def _to_challenge(snap) -> Challenge:
    d = snap.to_dict()
    return Challenge(
        id=uuid.UUID(snap.id),
        creator_id=uuid.UUID(d["creator_id"]),
        title=d["title"],
        exercise_id=d.get("exercise_id"),
        target_reps=int(d["target_reps"]),
        starts_at=d["starts_at"],
        ends_at=d["ends_at"],
        created_at=d["created_at"],
        participant_ids=tuple(uuid.UUID(p) for p in d.get("participant_ids") or []),
    )


async def create(
    *,
    challenge_id: uuid.UUID,
    creator_id: uuid.UUID,
    title: str,
    exercise_id: str | None,
    target_reps: int,
    starts_at: datetime,
    ends_at: datetime,
) -> bool:
    """Oluşturur, kurucuyu katılımcı yapar. Kimlik zaten varsa `False`."""
    try:
        await _col().document(str(challenge_id)).create({
            "creator_id": str(creator_id),
            "title": title,
            "exercise_id": exercise_id,
            "target_reps": target_reps,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "created_at": datetime.now(timezone.utc),
            "participant_ids": [str(creator_id)],
        })
        return True
    except AlreadyExists:
        return False


async def find_by_id(challenge_id: uuid.UUID) -> Challenge | None:
    snap = await _col().document(str(challenge_id)).get()
    return _to_challenge(snap) if snap.exists else None


async def join(challenge_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """`ArrayUnion` idempotent — ON CONFLICT DO NOTHING'in karşılığı."""
    await _col().document(str(challenge_id)).update({"participant_ids": firestore.ArrayUnion([str(user_id)])})


async def list_for_user(user_id: uuid.UUID) -> list[Challenge]:
    """Katıldığı TÜM meydan okumalar (bitmişler dahil), bitişe göre yeniden eskiye."""
    query = _col().where(filter=firestore.FieldFilter("participant_ids", "array_contains", str(user_id)))
    items = [_to_challenge(s) async for s in query.stream()]
    return sorted(items, key=lambda c: c.ends_at, reverse=True)


async def list_participants(challenge: Challenge) -> list[dict]:
    """Katılımcı + profil (LEFT JOIN: profili silinmiş katılımcı adsız döner)."""
    by_id = await profiles.profiles_map(challenge.participant_ids)
    rows = []
    for uid in challenge.participant_ids:
        p = by_id.get(uid)
        rows.append({
            "user_id": uid,
            "username": p.username if p else None,
            "display_name": p.display_name if p else None,
            "avatar_seed": p.avatar_seed if p else None,
        })
    return rows


async def fetch_progress(
    user_ids: list[uuid.UUID],
    starts_at: datetime,
    ends_at: datetime,
    exercise_id: str | None,
) -> dict[uuid.UUID, int]:
    """Katılımcı başına aralıktaki tekrar toplamı; `exercise_id` None ise
    egzersiz filtresi yok. Egzersiz filtresi bellekte (bileşik indeks olmasın)."""
    per_user = await asyncio.gather(*(snapshots.fetch_between(u, starts_at, ends_at) for u in user_ids))
    result = {}
    for user_id, snaps in zip(user_ids, per_user):
        reps = sum(int(s.get("total_reps", 0)) for s in snaps
                   if exercise_id is None or s.get("exercise_id") == exercise_id)
        if snaps:
            result[user_id] = reps
    return result


async def delete_for_user(user_id: uuid.UUID) -> None:
    uid = str(user_id)
    async for snap in _col().where(filter=firestore.FieldFilter("participant_ids", "array_contains", uid)).stream():
        if snap.get("creator_id") == uid:
            await snap.reference.delete()
        else:
            await snap.reference.update({"participant_ids": firestore.ArrayRemove([uid])})
    async for snap in _col().where(filter=firestore.FieldFilter("creator_id", "==", uid)).stream():
        await snap.reference.delete()


# --- Kudos ---------------------------------------------------------------------


async def give_kudos(workout_id: uuid.UUID, giver_id: uuid.UUID) -> bool:
    """Yeni ise `True` — `create()` ikinci kez AlreadyExists fırlatır."""
    try:
        await _kudos().document(f"{workout_id}_{giver_id}").create(
            {"workout_id": str(workout_id), "giver_id": str(giver_id), "created_at": firestore.SERVER_TIMESTAMP}
        )
        return True
    except AlreadyExists:
        return False


async def remove_kudos(workout_id: uuid.UUID, giver_id: uuid.UUID) -> None:
    await _kudos().document(f"{workout_id}_{giver_id}").delete()


async def count_kudos(workout_id: uuid.UUID) -> int:
    result = await _kudos().where(filter=firestore.FieldFilter("workout_id", "==", str(workout_id))).count().get()
    return int(result[0][0].value)


async def has_kudos(workout_id: uuid.UUID, giver_id: uuid.UUID) -> bool:
    return (await _kudos().document(f"{workout_id}_{giver_id}").get()).exists


async def delete_kudos_by_giver(giver_id: uuid.UUID) -> None:
    async for snap in _kudos().where(filter=firestore.FieldFilter("giver_id", "==", str(giver_id))).stream():
        await snap.reference.delete()
