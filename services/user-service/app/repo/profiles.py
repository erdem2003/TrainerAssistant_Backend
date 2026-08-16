"""profiles tablosunun SQL'i."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_SELECT_BY_ID = """
SELECT user_id, sex, age, weight_kg, height_cm, goal,
       unit_system, daily_goal_reps, onboarding_completed_at,
       created_at, updated_at
  FROM profiles
 WHERE user_id = $1
"""

# UPSERT — profil satırı TEMBEL oluşturuluyor.
_UPSERT = """
INSERT INTO profiles (
    user_id, sex, age, weight_kg, height_cm, goal,
    unit_system, daily_goal_reps, onboarding_completed_at, updated_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
ON CONFLICT (user_id) DO UPDATE SET
    sex                     = EXCLUDED.sex,
    age                     = EXCLUDED.age,
    weight_kg               = EXCLUDED.weight_kg,
    height_cm               = EXCLUDED.height_cm,
    goal                    = EXCLUDED.goal,
    unit_system             = EXCLUDED.unit_system,
    daily_goal_reps         = EXCLUDED.daily_goal_reps,
    -- BİR KEZ YAZILIR, SONRA KORUNUR: kullanıcı profilini sonradan
    -- düzenlediğinde onboarding tarihi güncellenmemeli — o, akışın ne zaman
    -- tamamlandığını söyleyen bir kayıt, son düzenleme zamanı değil
    -- (onun için `updated_at` var).
    onboarding_completed_at = COALESCE(profiles.onboarding_completed_at,
                                       EXCLUDED.onboarding_completed_at),
    updated_at              = now()
RETURNING user_id, sex, age, weight_kg, height_cm, goal,
          unit_system, daily_goal_reps, onboarding_completed_at,
          created_at, updated_at
"""

_DELETE_BY_ID = "DELETE FROM profiles WHERE user_id = $1"


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


def _to_profile(row: asyncpg.Record) -> Profile:
    return Profile(
        user_id=row["user_id"],
        sex=row["sex"],
        age=row["age"],
        weight_kg=row["weight_kg"],
        height_cm=row["height_cm"],
        goal=row["goal"],
        unit_system=row["unit_system"],
        daily_goal_reps=row["daily_goal_reps"],
        onboarding_completed_at=row["onboarding_completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def find_by_id(conn: asyncpg.Connection, user_id: uuid.UUID) -> Profile | None:
    row = await conn.fetchrow(_SELECT_BY_ID, user_id)
    return _to_profile(row) if row else None


async def upsert(
    conn: asyncpg.Connection,
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
    row = await conn.fetchrow(
        _UPSERT,
        user_id,
        sex,
        age,
        weight_kg,
        height_cm,
        goal,
        unit_system,
        daily_goal_reps,
        onboarding_completed_at,
    )
    return _to_profile(row)


async def delete_by_id(conn: asyncpg.Connection, user_id: uuid.UUID) -> bool:
    """Satırı siler. Satır yoksa `False` döner ama bu bir hata DEĞİL."""
    result = await conn.execute(_DELETE_BY_ID, user_id)
    return result != "DELETE 0"
