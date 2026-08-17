"""plan_items tablosunun SQL'i — gunluk antrenman programi.

Tamamlanma BU TABLODA TUTULMUYOR; `done_reps()` ile antrenman kayitlarindan
turetiliyor. Gerekcesi migrations/003_plan.sql basinda yazili.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import asyncpg

# --- Okuma ------------------------------------------------------------------

SELECT_DAY = """
SELECT id, exercise_id, target_reps, scheduled_time, position
  FROM plan_items
 WHERE user_id = $1 AND scheduled_date = $2
 ORDER BY position
"""

SELECT_RANGE = """
SELECT scheduled_date, exercise_id, target_reps, scheduled_time, position
  FROM plan_items
 WHERE user_id = $1 AND scheduled_date BETWEEN $2 AND $3
 ORDER BY scheduled_date, position
"""

# ★ TAMAMLANMANIN TEK KAYNAGI ★
#
# Tekrarlar SAYILIYOR, toplanmiyor: `reps` tablosunda tekrar basina bir satir
# var (001_initial.sql §reps), yani COUNT dogrudan tekrar sayisi demek.
#
# Gun siniri PARAMETRE olarak geliyor (UTC yarim acik aralik), cunku sunucu
# istemcinin saat dilimini bilmiyor. Burada `DATE(started_at)` kullanmak,
# Istanbul'da gece 01:00'de yapilan antrenmani bir onceki gune yazardi.
SELECT_DONE_REPS = """
SELECT w.exercise_id, COUNT(r.id) AS done_reps
  FROM workouts w
  JOIN sets s ON s.workout_id = w.id
  JOIN reps r ON r.set_id = s.id
 WHERE w.user_id = $1 AND w.started_at >= $2 AND w.started_at < $3
 GROUP BY w.exercise_id
"""

# Aralik icin ayni sayim, ama gune gore gruplanmis.
#
# Gun etiketi `w.started_at`'e saat dilimi farki EKLENEREK cikariliyor: sunucu
# UTC saklıyor, kullanicinin takvimi kaymis durumda. `$2` interval olarak
# geliyor (ornegin '180 minutes').
#
# ★ `AT TIME ZONE 'UTC'` ATLANMAZ ★
# `timestamptz::date` donusumu Postgres'in OTURUM saat dilimini (`TimeZone` GUC)
# kullanir. Konteynerde bu genelde UTC'dir ama garanti degil ve degistiginde
# gun etiketleri sessizce kayardi — hata da vermezdi. `AT TIME ZONE 'UTC'`
# once naif bir `timestamp` uretiyor; ondan sonraki `::date` saat diliminden
# tamamen bagimsiz.
SELECT_DONE_REPS_RANGE = """
SELECT (((w.started_at AT TIME ZONE 'UTC') + $2::interval))::date AS local_date,
       w.exercise_id,
       COUNT(r.id) AS done_reps
  FROM workouts w
  JOIN sets s ON s.workout_id = w.id
  JOIN reps r ON r.set_id = s.id
 WHERE w.user_id = $1 AND w.started_at >= $3 AND w.started_at < $4
 GROUP BY local_date, w.exercise_id
"""

# --- Yazma ------------------------------------------------------------------

DELETE_DAY = "DELETE FROM plan_items WHERE user_id = $1 AND scheduled_date = $2"

INSERT_ITEM = """
INSERT INTO plan_items
       (user_id, scheduled_date, exercise_id, target_reps, scheduled_time, position)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id
"""

DELETE_BY_USER = "DELETE FROM plan_items WHERE user_id = $1"


@dataclass(frozen=True)
class PlanRow:
    id: uuid.UUID
    exercise_id: str
    target_reps: int
    scheduled_time: time | None
    position: int


@dataclass(frozen=True)
class PlanRangeRow:
    scheduled_date: date
    exercise_id: str
    target_reps: int
    scheduled_time: time | None
    position: int


async def fetch_day(
    conn: asyncpg.Connection, user_id: uuid.UUID, day: date
) -> list[PlanRow]:
    rows = await conn.fetch(SELECT_DAY, user_id, day)
    return [
        PlanRow(
            id=row["id"],
            exercise_id=row["exercise_id"],
            target_reps=row["target_reps"],
            scheduled_time=row["scheduled_time"],
            position=row["position"],
        )
        for row in rows
    ]


async def fetch_range(
    conn: asyncpg.Connection, user_id: uuid.UUID, start: date, end: date
) -> list[PlanRangeRow]:
    rows = await conn.fetch(SELECT_RANGE, user_id, start, end)
    return [
        PlanRangeRow(
            scheduled_date=row["scheduled_date"],
            exercise_id=row["exercise_id"],
            target_reps=row["target_reps"],
            scheduled_time=row["scheduled_time"],
            position=row["position"],
        )
        for row in rows
    ]


async def done_reps(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, int]:
    """`exercise_id` -> o gun yapilan tekrar sayisi."""
    rows = await conn.fetch(SELECT_DONE_REPS, user_id, start_utc, end_utc)
    return {row["exercise_id"]: row["done_reps"] for row in rows}


async def done_reps_by_day(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    offset_minutes: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[date, dict[str, int]]:
    """`yerel gun` -> (`exercise_id` -> tekrar). Gun seridi isaretleri icin.

    Saat dilimi farki `timedelta` OLARAK geciliyor, metin olarak degil: asyncpg
    `interval` parametresini `timedelta`'dan kodluyor ve `'180 minutes'` gibi bir
    metin `AttributeError: 'str' object has no attribute 'days'` veriyor.
    `$2::interval` cast'i bunu kurtarmiyor cunku hata SQL'e gitmeden, parametre
    kodlanirken olusuyor.
    """
    rows = await conn.fetch(
        SELECT_DONE_REPS_RANGE,
        user_id,
        timedelta(minutes=offset_minutes),
        start_utc,
        end_utc,
    )
    result: dict[date, dict[str, int]] = {}
    for row in rows:
        result.setdefault(row["local_date"], {})[row["exercise_id"]] = row["done_reps"]
    return result


async def replace_day(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    day: date,
    items: list,
) -> None:
    """Gunun listesini KOMPLE degistirir.

    KISMI GUNCELLEME YOK (profil ucuyla ayni desen): istemci elindeki tam
    listeyi yaziyor. Boylece ekleme, silme ve siralama TEK istekte cozuluyor ve
    ucun kendisi dogal olarak idempotent oluyor.

    CAGIRAN TARAF TRANSACTION ACMALI: silme basarili olup ekleme patlarsa
    kullanicinin programi sessizce silinmis olurdu.
    """
    await conn.execute(DELETE_DAY, user_id, day)
    for position, item in enumerate(items, start=1):
        await conn.execute(
            INSERT_ITEM,
            user_id,
            day,
            item.exercise_id,
            item.target_reps,
            item.scheduled_time,
            position,
        )


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    """Hesap silme zinciri — kullanicinin tum plan kalemleri."""
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])
