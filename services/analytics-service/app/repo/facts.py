"""workout_facts tablosunun SQL'i — olay akisinin izdusumu."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import asyncpg

# ★ ON CONFLICT DO UPDATE, DO NOTHING DEGIL ★
# Replay sirasinda satirlar zaten var; DO NOTHING olsaydi yeniden oynatma
# HICBIR SEY degistirmezdi ve hesap mantigi degistiginde eski sonuc kalirdi.
# Replay'in anlami tam olarak "ayni olaydan guncel mantikla yeniden uret".
UPSERT_FACT = """
INSERT INTO workout_facts (
    workout_id, user_id, exercise_id, started_at, ended_at,
    total_sets, total_reps, reps_with_errors, best_set_reps,
    total_active_seconds, form_errors, projected_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, now())
ON CONFLICT (workout_id) DO UPDATE SET
    user_id              = EXCLUDED.user_id,
    exercise_id          = EXCLUDED.exercise_id,
    started_at           = EXCLUDED.started_at,
    ended_at             = EXCLUDED.ended_at,
    total_sets           = EXCLUDED.total_sets,
    total_reps           = EXCLUDED.total_reps,
    reps_with_errors     = EXCLUDED.reps_with_errors,
    best_set_reps        = EXCLUDED.best_set_reps,
    total_active_seconds = EXCLUDED.total_active_seconds,
    form_errors          = EXCLUDED.form_errors,
    projected_at         = now()
"""

# Gun etiketi `AT TIME ZONE 'UTC'` ile naif timestamp'e cevrilip saat dilimi
# farki EKLENEREK cikariliyor — workout-service `repo/stats.py` ile ayni desen
# ve ayni gerekce: dogrudan `timestamptz::date` Postgres'in OTURUM saat
# dilimine baglanir ve o degistiginde gun etiketleri sessizce kayar.
SELECT_DAILY = """
SELECT (((started_at AT TIME ZONE 'UTC') + $2::interval))::date AS local_date,
       exercise_id,
       COUNT(*)                        AS workouts,
       SUM(total_sets)                 AS sets,
       SUM(total_reps)                 AS reps,
       SUM(reps_with_errors)           AS reps_with_errors,
       SUM(total_active_seconds)       AS active_seconds
  FROM workout_facts
 WHERE user_id = $1 AND started_at >= $3 AND started_at < $4
 GROUP BY local_date, exercise_id
 ORDER BY local_date, exercise_id
"""

DELETE_BY_USER = "DELETE FROM workout_facts WHERE user_id = $1"

COUNT_ALL = "SELECT COUNT(*) FROM workout_facts"


@dataclass(frozen=True)
class ExerciseDayRow:
    local_date: date
    exercise_id: str
    workouts: int
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float


async def upsert(
    conn: asyncpg.Connection,
    *,
    workout_id: uuid.UUID,
    user_id: uuid.UUID,
    exercise_id: str,
    started_at: datetime,
    ended_at: datetime | None,
    total_sets: int,
    total_reps: int,
    reps_with_errors: int,
    best_set_reps: int,
    total_active_seconds: float,
    form_errors: dict,
) -> None:
    await conn.execute(
        UPSERT_FACT,
        workout_id, user_id, exercise_id, started_at, ended_at,
        total_sets, total_reps, reps_with_errors, best_set_reps,
        total_active_seconds, json.dumps(form_errors),
    )


async def fetch_daily(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    offset_minutes: int,
    start_utc: datetime,
    end_utc: datetime,
) -> list[ExerciseDayRow]:
    rows = await conn.fetch(
        SELECT_DAILY,
        user_id,
        timedelta(minutes=offset_minutes),
        start_utc,
        end_utc,
    )
    return [
        ExerciseDayRow(
            local_date=row["local_date"],
            exercise_id=row["exercise_id"],
            workouts=row["workouts"],
            sets=row["sets"],
            reps=row["reps"],
            reps_with_errors=row["reps_with_errors"],
            active_seconds=float(row["active_seconds"]),
        )
        for row in rows
    ]


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])


async def count_all(conn: asyncpg.Connection) -> int:
    """Replay dogrulamasi icin: yeniden oynatma satir sayisini DEGISTIRMEMELI."""
    return await conn.fetchval(COUNT_ALL)
