"""Profil — `user_users/{user_id}` kök dokümanı."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import firestore

from app.db import db, user_doc


@dataclass(frozen=True)
class Profile:
    user_id: uuid.UUID
    sex: str | None
    age: int | None
    weight_kg: float | None
    height_cm: float | None
    goal: str | None
    unit_system: str
    daily_goal_reps: int
    onboarding_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _to_profile(user_id: uuid.UUID, data: dict) -> Profile:
    return Profile(
        user_id=user_id,
        sex=data.get("sex"),
        age=data.get("age"),
        weight_kg=data.get("weight_kg"),
        height_cm=data.get("height_cm"),
        goal=data.get("goal"),
        unit_system=data.get("unit_system", "METRIC"),
        daily_goal_reps=int(data.get("daily_goal_reps", 20)),
        onboarding_completed_at=data.get("onboarding_completed_at"),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


async def find_by_id(user_id: uuid.UUID) -> Profile | None:
    snap = await user_doc(user_id).get()
    data = snap.to_dict() if snap.exists else None
    if not data or "created_at" not in data:
        return None
    return _to_profile(user_id, data)


async def upsert(
    user_id: uuid.UUID,
    *,
    sex: str | None,
    age: int | None,
    weight_kg: float | None,
    height_cm: float | None,
    goal: str | None,
    unit_system: str,
    daily_goal_reps: int,
    onboarding_completed_at: datetime | None,
) -> Profile:
    """Profili TAM değiştirir; doküman yoksa oluşturur.

    ★ TRANSACTION ★ İki alan korunuyor ve ikisi de mevcut değeri okumayı
    gerektiriyor: `created_at` (ilk yazımın zamanı) ve
    `onboarding_completed_at` (BİR KEZ yazılır — Postgres'teki
    `COALESCE(profiles.onboarding_completed_at, EXCLUDED...)`). Oku-sonra-yaz
    transaction dışında yapılsaydı iki paralel PUT birbirinin tarihini ezebilirdi.

    Zaman damgaları `SERVER_TIMESTAMP` değil sürecin saatiyle yazılıyor: yanıt
    aynı değerleri döndürmek zorunda ve sunucu damgası yazımdan sonra ikinci
    bir okuma isterdi.
    """
    ref = user_doc(user_id)
    now = datetime.now(timezone.utc)

    @firestore.async_transactional
    async def run(tx) -> dict:
        snap = await ref.get(transaction=tx)
        current = (snap.to_dict() or {}) if snap.exists else {}
        data = {
            "sex": sex,
            "age": age,
            "weight_kg": weight_kg,
            "height_cm": height_cm,
            "goal": goal,
            "unit_system": unit_system,
            "daily_goal_reps": daily_goal_reps,
            "onboarding_completed_at": current.get("onboarding_completed_at") or onboarding_completed_at,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
        }
        tx.set(ref, data)
        return data

    return _to_profile(user_id, await run(db.client.transaction()))
