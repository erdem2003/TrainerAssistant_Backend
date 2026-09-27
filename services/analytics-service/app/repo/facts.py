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

# B1 — hata dagilimi. `form_errors` `{"HIP_SAG": 3, ...}` seklinde JSONB;
# jsonb_each_text ile satir satir acilip aralik icinde toplaniyor. Ayni
# sorguda araliktaki TOPLAM tekrar da doner — yuzdeyi cikaran istemci tarafi.
# `$4` NULL ise tüm egzersizler; değilse yalnız o egzersiz (İlerleme / Hata
# dağılımı ekranının egzersiz çipleri).
SELECT_ERROR_COUNTS = """
SELECT key AS error_name, SUM(value::int) AS occurrences
  FROM workout_facts, jsonb_each_text(form_errors)
 WHERE user_id = $1 AND started_at >= $2 AND started_at < $3
   AND ($4::text IS NULL OR exercise_id = $4)
 GROUP BY key
 ORDER BY occurrences DESC
"""

SELECT_TOTAL_REPS_IN_RANGE = """
SELECT COALESCE(SUM(total_reps), 0) AS total_reps,
       COALESCE(SUM(reps_with_errors), 0) AS reps_with_errors
  FROM workout_facts
 WHERE user_id = $1 AND started_at >= $2 AND started_at < $3
   AND ($4::text IS NULL OR exercise_id = $4)
"""

# A2 — rozetler icin tek sorguda toplanan istatistikler.
# `best_clean_ratio` en az 5 tekrarlik setleri dikkate alir: 1 tekrarlik
# sansli bir set %100 gorunup rozeti anlamsizlastirmasin diye.
SELECT_BADGE_STATS = """
SELECT
    COALESCE(SUM(total_reps), 0) AS total_reps,
    MAX(
        CASE WHEN total_reps >= 5
             THEN (total_reps - reps_with_errors)::float / total_reps
        END
    ) AS best_clean_ratio,
    EXISTS(
        SELECT 1 FROM workout_facts WHERE user_id = $1 AND exercise_id = 'squat'
    ) AS has_squat,
    EXISTS(
        SELECT 1 FROM workout_facts
         WHERE user_id = $1
           AND EXTRACT(HOUR FROM ((started_at AT TIME ZONE 'UTC') + $2::interval)) < 8
    ) AS has_early_bird,
    EXISTS(
        SELECT 1 FROM workout_facts
         WHERE user_id = $1
           AND EXTRACT(HOUR FROM ((started_at AT TIME ZONE 'UTC') + $2::interval)) >= 22
    ) AS has_night_owl
  FROM workout_facts
 WHERE user_id = $1
"""

SELECT_ACTIVE_LOCAL_DATES = """
SELECT DISTINCT (((started_at AT TIME ZONE 'UTC') + $2::interval))::date AS local_date
  FROM workout_facts
 WHERE user_id = $1
"""


@dataclass(frozen=True)
class ErrorCountRow:
    error_name: str
    occurrences: int


@dataclass(frozen=True)
class BadgeStats:
    total_reps: int
    best_clean_ratio: float | None
    has_squat: bool
    has_early_bird: bool
    has_night_owl: bool
    active_local_dates: list[date]


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


async def fetch_error_counts(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
    exercise_id: str | None = None,
) -> tuple[list[ErrorCountRow], int, int]:
    """(hata sayıları, toplam tekrar, hatalı tekrar)."""
    rows = await conn.fetch(SELECT_ERROR_COUNTS, user_id, start_utc, end_utc, exercise_id)
    totals = await conn.fetchrow(
        SELECT_TOTAL_REPS_IN_RANGE, user_id, start_utc, end_utc, exercise_id
    )
    return (
        [ErrorCountRow(error_name=r["error_name"], occurrences=r["occurrences"]) for r in rows],
        int(totals["total_reps"]),
        int(totals["reps_with_errors"]),
    )


async def fetch_badge_stats(
    conn: asyncpg.Connection, user_id: uuid.UUID, offset_minutes: int
) -> BadgeStats:
    offset = timedelta(minutes=offset_minutes)
    stats_row = await conn.fetchrow(SELECT_BADGE_STATS, user_id, offset)
    date_rows = await conn.fetch(SELECT_ACTIVE_LOCAL_DATES, user_id, offset)
    return BadgeStats(
        total_reps=int(stats_row["total_reps"]),
        best_clean_ratio=stats_row["best_clean_ratio"],
        has_squat=stats_row["has_squat"],
        has_early_bird=stats_row["has_early_bird"],
        has_night_owl=stats_row["has_night_owl"],
        active_local_dates=[r["local_date"] for r in date_rows],
    )
