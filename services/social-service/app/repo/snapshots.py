"""workout_snapshots tablosunun SQL'i — `workout.session` akisinin izdusumu.

`analytics-service/app/repo/facts.py` ile ayni desen (ayni UPSERT gerekcesi:
replay'in ayni olaydan guncel mantikla yeniden uretmesi icin `DO UPDATE`,
`DO NOTHING` degil) ama BAGIMSIZ kod — servisler kod paylasmiyor (ADR 0005).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import asyncpg

UPSERT_SNAPSHOT = """
INSERT INTO workout_snapshots (
    workout_id, user_id, exercise_id, started_at, ended_at,
    total_sets, total_reps, reps_with_errors, best_set_reps,
    total_active_seconds, form_errors, projected_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, now())
ON CONFLICT (workout_id) DO UPDATE SET
    user_id               = EXCLUDED.user_id,
    exercise_id           = EXCLUDED.exercise_id,
    started_at            = EXCLUDED.started_at,
    ended_at               = EXCLUDED.ended_at,
    total_sets             = EXCLUDED.total_sets,
    total_reps             = EXCLUDED.total_reps,
    reps_with_errors       = EXCLUDED.reps_with_errors,
    best_set_reps          = EXCLUDED.best_set_reps,
    total_active_seconds   = EXCLUDED.total_active_seconds,
    form_errors             = EXCLUDED.form_errors,
    projected_at            = now()
"""

DELETE_BY_USER = "DELETE FROM workout_snapshots WHERE user_id = $1"

COUNT_ALL = "SELECT COUNT(*) FROM workout_snapshots"

# ★ HAFTALIK SKOR TABLOSU (Faz S5) ★ Tek sorguda kullanıcı başına toplanan
# ham bileşenler — puanlama formülü BURADA DEĞİL, `app/scoring.py`'de (skor
# nasıl hesaplandığı UI'ya da göründüğü için ayrık tutuluyor, ADR 0012 "sorgu
# anında" ilkesiyle aynı ruh: hiçbir şey saklanmıyor, hepsi bu sorgudan türer).
# `active_days`, izleyicinin KENDİ saat dilimiyle ($4) hesaplanıyor — herkes
# aynı hafta penceresiyle karşılaştırılıyor, her arkadaşın kendi saat dilimi
# değil (aksi halde "bu hafta" farklı kullanıcılar için farklı aralıklar olur
# ve sıralama anlamsızlaşır).
SELECT_WEEKLY_STATS = """
SELECT user_id,
       COALESCE(SUM(total_reps), 0) AS total_reps,
       COALESCE(SUM(GREATEST(total_reps - reps_with_errors, 0)), 0) AS clean_reps,
       COALESCE(SUM(total_sets), 0) AS total_sets,
       COUNT(DISTINCT (((started_at AT TIME ZONE 'UTC') + $4::interval))::date) AS active_days
  FROM workout_snapshots
 WHERE user_id = ANY($1::uuid[]) AND started_at >= $2 AND started_at < $3
 GROUP BY user_id
"""


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
        UPSERT_SNAPSHOT,
        workout_id, user_id, exercise_id, started_at, ended_at,
        total_sets, total_reps, reps_with_errors, best_set_reps,
        total_active_seconds, json.dumps(form_errors),
    )


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])


async def count_all(conn: asyncpg.Connection) -> int:
    """Replay dogrulamasi icin: yeniden oynatma satir sayisini DEGISTIRMEMELI."""
    return await conn.fetchval(COUNT_ALL)


async def fetch_weekly_stats(
    conn: asyncpg.Connection,
    user_ids: list[uuid.UUID],
    start_utc: datetime,
    end_utc: datetime,
    offset_minutes: int,
) -> list[asyncpg.Record]:
    """Faz S5 (haftalik skor tablosu): kullanici basina ham bilesenler —
    puanlama formulu cagiran tarafta (app/scoring.py) hesaplanir."""
    return await conn.fetch(
        SELECT_WEEKLY_STATS, user_ids, start_utc, end_utc, timedelta(minutes=offset_minutes)
    )
