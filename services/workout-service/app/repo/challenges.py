"""Katılınan 30 günlük meydan okumalar — yalnız başlangıç günü saklanır.

    workout_users/{uid}/challenges/{challenge_id}   {started_on: "YYYY-MM-DD", joined_at}

Bir meydan okumadan aynı anda tek kayıt: yeniden başlamak kaydın üzerine yazar.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.db import user_doc


def _col(user_id: uuid.UUID):
    return user_doc(user_id).collection("challenges")


async def list_joined(user_id: uuid.UUID) -> dict[str, date]:
    return {
        snap.id: date.fromisoformat(snap.get("started_on"))
        async for snap in _col(user_id).stream()
    }


async def join(user_id: uuid.UUID, challenge_id: str, started_on: date) -> None:
    await _col(user_id).document(challenge_id).set(
        {"started_on": started_on.isoformat(), "joined_at": datetime.now(timezone.utc)}
    )


async def leave(user_id: uuid.UUID, challenge_id: str) -> None:
    await _col(user_id).document(challenge_id).delete()
