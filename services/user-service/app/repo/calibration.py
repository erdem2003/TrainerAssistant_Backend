"""calibration_profiles tablosunun SQL'i — kişisel eşik ölçümü (D1)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

SELECT_ONE = """
SELECT exercise_id, sample_count, measured_values, calibrated_at
  FROM calibration_profiles
 WHERE user_id = $1 AND exercise_id = $2
"""

SELECT_ALL = """
SELECT exercise_id, sample_count, measured_values, calibrated_at
  FROM calibration_profiles
 WHERE user_id = $1
 ORDER BY exercise_id
"""

UPSERT = """
INSERT INTO calibration_profiles (user_id, exercise_id, sample_count, measured_values, calibrated_at)
VALUES ($1, $2, $3, $4::jsonb, now())
ON CONFLICT (user_id, exercise_id) DO UPDATE
   SET sample_count    = EXCLUDED.sample_count,
       measured_values = EXCLUDED.measured_values,
       calibrated_at   = now()
RETURNING exercise_id, sample_count, measured_values, calibrated_at
"""

DELETE_BY_USER = "DELETE FROM calibration_profiles WHERE user_id = $1"


@dataclass(frozen=True)
class CalibrationRow:
    exercise_id: str
    sample_count: int
    measured_values: dict[str, float]
    calibrated_at: datetime


def _to_row(row: asyncpg.Record) -> CalibrationRow:
    return CalibrationRow(
        exercise_id=row["exercise_id"],
        sample_count=row["sample_count"],
        measured_values=json.loads(row["measured_values"]),
        calibrated_at=row["calibrated_at"],
    )


async def upsert(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    exercise_id: str,
    sample_count: int,
    measured_values: dict[str, float],
) -> CalibrationRow:
    row = await conn.fetchrow(
        UPSERT, user_id, exercise_id, sample_count, json.dumps(measured_values)
    )
    return _to_row(row)


async def fetch_one(
    conn: asyncpg.Connection, user_id: uuid.UUID, exercise_id: str
) -> CalibrationRow | None:
    row = await conn.fetchrow(SELECT_ONE, user_id, exercise_id)
    return _to_row(row) if row else None


async def fetch_all(
    conn: asyncpg.Connection, user_id: uuid.UUID
) -> list[CalibrationRow]:
    rows = await conn.fetch(SELECT_ALL, user_id)
    return [_to_row(row) for row in rows]


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])
