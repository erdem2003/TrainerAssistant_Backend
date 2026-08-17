"""sleep_logs tablosunun SQL'i — gecelik uyku suresi."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import asyncpg

SELECT_DAY = """
SELECT log_date, minutes FROM sleep_logs
 WHERE user_id = $1 AND log_date = $2
"""

SELECT_RANGE = """
SELECT log_date, minutes FROM sleep_logs
 WHERE user_id = $1 AND log_date BETWEEN $2 AND $3
 ORDER BY log_date
"""

# ★ SU'DAN FARKLI: EKLEME DEGIL, UZERINE YAZMA ★
# Su gun icinde birikiyor ("200 ml daha ictim"); uyku ise tek bir olcum ve
# duzeltiliyor ("7 degil 7.5 saat uyumusum"). Bu yuzden yalnizca `set` var,
# `add` yok — birikimli bir uyku ucu, iki kez kaydedince 14 saat uretirdi.
SET_MINUTES = """
INSERT INTO sleep_logs (user_id, log_date, minutes)
VALUES ($1, $2, $3)
ON CONFLICT (user_id, log_date) DO UPDATE
   SET minutes = EXCLUDED.minutes,
       updated_at = now()
RETURNING log_date, minutes
"""

DELETE_DAY = "DELETE FROM sleep_logs WHERE user_id = $1 AND log_date = $2"

DELETE_BY_USER = "DELETE FROM sleep_logs WHERE user_id = $1"


@dataclass(frozen=True)
class SleepRow:
    log_date: date
    minutes: int


async def fetch_day(
    conn: asyncpg.Connection, user_id: uuid.UUID, day: date
) -> SleepRow | None:
    row = await conn.fetchrow(SELECT_DAY, user_id, day)
    if row is None:
        return None
    return SleepRow(log_date=row["log_date"], minutes=row["minutes"])


async def fetch_range(
    conn: asyncpg.Connection, user_id: uuid.UUID, start: date, end: date
) -> list[SleepRow]:
    rows = await conn.fetch(SELECT_RANGE, user_id, start, end)
    return [
        SleepRow(log_date=row["log_date"], minutes=row["minutes"]) for row in rows
    ]


async def set_minutes(
    conn: asyncpg.Connection, user_id: uuid.UUID, day: date, minutes: int
) -> SleepRow:
    row = await conn.fetchrow(SET_MINUTES, user_id, day, minutes)
    return SleepRow(log_date=row["log_date"], minutes=row["minutes"])


async def delete_day(
    conn: asyncpg.Connection, user_id: uuid.UUID, day: date
) -> int:
    """Kaydi tamamen siler.

    `minutes = 0` YAZMAKTAN FARKLI: sifir "hic uyumadim" demek, kaydin
    olmamasi "girmedim" demek. Ortalama hesabinda ikisi farkli davranmali —
    sifirlar ortalamayi asagi ceker, kayitsiz gunler hesaba girmez.
    """
    result = await conn.execute(DELETE_DAY, user_id, day)
    return int(result.rsplit(" ", 1)[1])


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])
