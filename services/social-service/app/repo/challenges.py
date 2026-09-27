"""challenges / challenge_participants / workout_kudos SQL (ADR 0014, Faz S9).

İlerleme burada HESAPLANMAZ — yalnızca hedef/katılımcı satırları. İlerleme
sorgusu `app/routers/challenges.py`'de `workout_snapshots`'a karşı çalışır.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_INSERT_CHALLENGE = """
INSERT INTO challenges (id, creator_id, title, exercise_id, target_reps, starts_at, ends_at)
VALUES ($1, $2, $3, $4, $5, $6, $7)
"""

_FIND_BY_ID = """
SELECT id, creator_id, title, exercise_id, target_reps, starts_at, ends_at, created_at
  FROM challenges WHERE id = $1
"""

_INSERT_PARTICIPANT = """
INSERT INTO challenge_participants (challenge_id, user_id) VALUES ($1, $2)
ON CONFLICT (challenge_id, user_id) DO NOTHING
"""

_IS_PARTICIPANT = "SELECT 1 FROM challenge_participants WHERE challenge_id = $1 AND user_id = $2"

# Kullanıcının katıldığı TÜM meydan okumalar — bitmiş olanlar da dahil
# (geçmişte kalan bir hedefi tamamlayıp tamamlamadığını görmek istenir).
_SELECT_FOR_USER = """
SELECT c.id, c.creator_id, c.title, c.exercise_id, c.target_reps, c.starts_at, c.ends_at, c.created_at
  FROM challenges c
  JOIN challenge_participants cp ON cp.challenge_id = c.id
 WHERE cp.user_id = $1
 ORDER BY c.ends_at DESC
"""

_SELECT_PARTICIPANTS = """
SELECT cp.user_id, p.username, p.display_name, p.avatar_seed
  FROM challenge_participants cp
  LEFT JOIN social_profiles p ON p.user_id = cp.user_id
 WHERE cp.challenge_id = $1
"""

# İlerleme: katılımcı başına, hedef egzersize (varsa) ve tarih aralığına göre
# `workout_snapshots` toplamı. `exercise_id IS NULL` ise egzersiz filtresi yok.
_SELECT_PROGRESS = """
SELECT user_id, COALESCE(SUM(total_reps), 0) AS reps
  FROM workout_snapshots
 WHERE user_id = ANY($1::uuid[])
   AND started_at >= $2 AND started_at < $3
   AND ($4::text IS NULL OR exercise_id = $4)
 GROUP BY user_id
"""

_DELETE_PARTICIPANT_BY_USER = "DELETE FROM challenge_participants WHERE user_id = $1"
_DELETE_CHALLENGES_BY_CREATOR = "DELETE FROM challenges WHERE creator_id = $1"

_UPSERT_KUDOS = """
INSERT INTO workout_kudos (workout_id, giver_id) VALUES ($1, $2)
ON CONFLICT (workout_id, giver_id) DO NOTHING
RETURNING workout_id
"""

_DELETE_KUDOS = "DELETE FROM workout_kudos WHERE workout_id = $1 AND giver_id = $2"

_COUNT_KUDOS = "SELECT COUNT(*) FROM workout_kudos WHERE workout_id = $1"

_HAS_KUDOS = "SELECT 1 FROM workout_kudos WHERE workout_id = $1 AND giver_id = $2"

_DELETE_KUDOS_BY_GIVER = "DELETE FROM workout_kudos WHERE giver_id = $1"


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


async def create(
    conn: asyncpg.Connection,
    *,
    challenge_id: uuid.UUID,
    creator_id: uuid.UUID,
    title: str,
    exercise_id: str | None,
    target_reps: int,
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    await conn.execute(
        _INSERT_CHALLENGE, challenge_id, creator_id, title, exercise_id, target_reps, starts_at, ends_at
    )
    await conn.execute(_INSERT_PARTICIPANT, challenge_id, creator_id)


async def find_by_id(conn: asyncpg.Connection, challenge_id: uuid.UUID) -> Challenge | None:
    row = await conn.fetchrow(_FIND_BY_ID, challenge_id)
    return Challenge(**dict(row)) if row else None


async def join(conn: asyncpg.Connection, challenge_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await conn.execute(_INSERT_PARTICIPANT, challenge_id, user_id)


async def is_participant(conn: asyncpg.Connection, challenge_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return await conn.fetchval(_IS_PARTICIPANT, challenge_id, user_id) is not None


async def list_for_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[Challenge]:
    rows = await conn.fetch(_SELECT_FOR_USER, user_id)
    return [Challenge(**dict(r)) for r in rows]


async def list_participants(conn: asyncpg.Connection, challenge_id: uuid.UUID) -> list[asyncpg.Record]:
    return await conn.fetch(_SELECT_PARTICIPANTS, challenge_id)


async def fetch_progress(
    conn: asyncpg.Connection,
    user_ids: list[uuid.UUID],
    starts_at: datetime,
    ends_at: datetime,
    exercise_id: str | None,
) -> dict[uuid.UUID, int]:
    rows = await conn.fetch(_SELECT_PROGRESS, user_ids, starts_at, ends_at, exercise_id)
    return {r["user_id"]: r["reps"] for r in rows}


async def delete_for_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> None:
    await conn.execute(_DELETE_PARTICIPANT_BY_USER, user_id)
    await conn.execute(_DELETE_CHALLENGES_BY_CREATOR, user_id)


async def give_kudos(conn: asyncpg.Connection, workout_id: uuid.UUID, giver_id: uuid.UUID) -> bool:
    row = await conn.fetchrow(_UPSERT_KUDOS, workout_id, giver_id)
    return row is not None


async def remove_kudos(conn: asyncpg.Connection, workout_id: uuid.UUID, giver_id: uuid.UUID) -> None:
    await conn.execute(_DELETE_KUDOS, workout_id, giver_id)


async def count_kudos(conn: asyncpg.Connection, workout_id: uuid.UUID) -> int:
    return await conn.fetchval(_COUNT_KUDOS, workout_id)


async def has_kudos(conn: asyncpg.Connection, workout_id: uuid.UUID, giver_id: uuid.UUID) -> bool:
    return await conn.fetchval(_HAS_KUDOS, workout_id, giver_id) is not None


async def delete_kudos_by_giver(conn: asyncpg.Connection, giver_id: uuid.UUID) -> None:
    await conn.execute(_DELETE_KUDOS_BY_GIVER, giver_id)
