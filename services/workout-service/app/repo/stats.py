"""Gunluk toplamlar — Istatistik ekraninin tek veri kaynagi.

★ NEDEN BU UC VAR ★
Istatistik ekrani gun bazinda kalori, tekrar, set ve form hatasi dagilimi
gosteriyor. Bunlari gecmis listesinden turetmek MUMKUN degildi: liste yaniti
tekrarlari ve hatalari tasimiyor (WorkoutSummary bilincli olarak sade), ayrintiya
inmek icin antrenman basina bir istek gerekirdi — 30 gunluk bir ekran icin
onlarca cagri.

★ BU MANTIK ILERIDE `analytics-service`'E TASINACAK ★
ADR 0006 toplama isini oraya veriyor. Ucun BICIMI o zaman degismeyecek; yalnizca
hesabin nerede yapildigi degisecek. Bu yuzden istemci bu ucu "gunluk toplamlar"
olarak taniyor, "workout-service'in bir ozelligi" olarak degil.

★ KALORI BURADA HESAPLANMIYOR ★
Yalnizca `active_seconds` donuyor. Kalori kilo ve MET gerektiriyor; kilo
`user-service`'te ve MET egzersiz katalogunun bilgisi. Sunucu tarafinda kalori
hesaplamak, bu servisi baska bir servisin verisine bagimli kilardi. Istemci
`core/health/HealthMetrics` ile hesapliyor — ADR 0010'un "kalori saklanmaz,
okunurken hesaplanir" karariyla ayni cizgi.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import asyncpg

# Gun etiketi `AT TIME ZONE 'UTC'` ile naif timestamp'e cevrilip sonra saat dilimi
# farki eklenerek cikariliyor. Dogrudan `timestamptz::date` kullanmak Postgres'in
# OTURUM saat dilimine baglanirdi ve o degistiginde gun etiketleri sessizce kayardi.
_DAY_WORKOUT_CTE = """
WITH day_workout AS (
    SELECT w.id,
           w.exercise_id,
           (((w.started_at AT TIME ZONE 'UTC') + $2::interval))::date AS local_date
      FROM workouts w
     WHERE w.user_id = $1 AND w.started_at >= $3 AND w.started_at < $4
)
"""

# ★ SET VE TEKRAR AYRI CTE'LERDE TOPLANIYOR ★
# Tek sorguda set × tekrar × hata JOIN'i yapilsaydi set sureleri her tekrar icin
# bir kez daha toplanir ve `active_seconds` kat kat sisirilirdi. Ayni tuzak
# `SELECT_WORKOUT_PAGE`'de `COUNT(DISTINCT ...)` ile cozulmus; toplama (SUM)
# icin DISTINCT bir cozum degil, granulariteyi ayirmak gerekiyor.
SELECT_DAILY = _DAY_WORKOUT_CTE + """
, set_agg AS (
    SELECT dw.local_date,
           dw.exercise_id,
           COUNT(s.id) AS sets,
           COALESCE(SUM(EXTRACT(EPOCH FROM (s.ended_at - s.started_at))), 0) AS active_seconds
      FROM day_workout dw
      LEFT JOIN sets s ON s.workout_id = dw.id
     GROUP BY dw.local_date, dw.exercise_id
),
rep_agg AS (
    SELECT dw.local_date,
           dw.exercise_id,
           COUNT(r.id) AS reps,
           COUNT(r.id) FILTER (WHERE faulty.rep_id IS NOT NULL) AS reps_with_errors
      FROM day_workout dw
      JOIN sets s ON s.workout_id = dw.id
      JOIN reps r ON r.set_id = s.id
      -- Tekrar basina EN FAZLA BIR satir: bir tekrarda iki hata varsa
      -- `reps_with_errors` iki kez saymamali.
      LEFT JOIN (SELECT DISTINCT rep_id FROM rep_form_errors) faulty
             ON faulty.rep_id = r.id
     GROUP BY dw.local_date, dw.exercise_id
),
workout_count AS (
    SELECT local_date, COUNT(*) AS workouts
      FROM day_workout
     GROUP BY local_date
)
SELECT sa.local_date,
       sa.exercise_id,
       sa.sets,
       sa.active_seconds,
       COALESCE(ra.reps, 0)             AS reps,
       COALESCE(ra.reps_with_errors, 0) AS reps_with_errors,
       wc.workouts
  FROM set_agg sa
  LEFT JOIN rep_agg ra
         ON ra.local_date = sa.local_date AND ra.exercise_id = sa.exercise_id
  JOIN workout_count wc ON wc.local_date = sa.local_date
 ORDER BY sa.local_date, sa.exercise_id
"""

# Form hatasi dagilimi — gun ve hata turune gore.
# Ayri sorgu, cunku ayni sonuc kumesine sigdirmak hata turu basina bir sutun ya da
# JSON toplama gerektirirdi; ikisi de okunmasi zor SQL uretiyor.
SELECT_DAILY_ERRORS = _DAY_WORKOUT_CTE + """
SELECT dw.local_date, e.error, COUNT(*) AS occurrences
  FROM day_workout dw
  JOIN sets s ON s.workout_id = dw.id
  JOIN reps r ON r.set_id = s.id
  JOIN rep_form_errors e ON e.rep_id = r.id
 GROUP BY dw.local_date, e.error
 ORDER BY dw.local_date, e.error
"""


@dataclass(frozen=True)
class ExerciseDayRow:
    local_date: date
    exercise_id: str
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float
    workouts: int


@dataclass(frozen=True)
class ErrorDayRow:
    local_date: date
    error: str
    occurrences: int


async def fetch_daily(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    offset_minutes: int,
    start_utc: datetime,
    end_utc: datetime,
) -> list[ExerciseDayRow]:
    """Gun × egzersiz kiriliminda toplamlar."""
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
            sets=row["sets"],
            reps=row["reps"],
            reps_with_errors=row["reps_with_errors"],
            # `EXTRACT(EPOCH ...)` numeric doner, asyncpg Decimal'e cevirir.
            # JSON'a Decimal yazmak istemedigimiz icin burada float'a duruyor.
            active_seconds=float(row["active_seconds"]),
            workouts=row["workouts"],
        )
        for row in rows
    ]


async def fetch_daily_errors(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    offset_minutes: int,
    start_utc: datetime,
    end_utc: datetime,
) -> list[ErrorDayRow]:
    """Gun × form hatasi kiriliminda tekrar sayilari."""
    rows = await conn.fetch(
        SELECT_DAILY_ERRORS,
        user_id,
        timedelta(minutes=offset_minutes),
        start_utc,
        end_utc,
    )
    return [
        ErrorDayRow(
            local_date=row["local_date"],
            error=row["error"],
            occurrences=row["occurrences"],
        )
        for row in rows
    ]
