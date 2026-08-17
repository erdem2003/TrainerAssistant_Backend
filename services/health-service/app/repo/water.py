"""water_logs tablosunun SQL'i — gunluk su tuketimi."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import asyncpg

SELECT_DAY = """
SELECT log_date, amount_ml FROM water_logs
 WHERE user_id = $1 AND log_date = $2
"""

SELECT_RANGE = """
SELECT log_date, amount_ml FROM water_logs
 WHERE user_id = $1 AND log_date BETWEEN $2 AND $3
 ORDER BY log_date
"""

# ★ UPSERT, SELECT-SONRA-INSERT DEGIL ★
# Iki paralel "su ekle" istegi ayni gune gelirse SELECT-then-INSERT deseninde
# ikisi de "satir yok" gorup INSERT dener; biri unique kisita takilir ve
# kullanicinin ekledigi su KAYBOLUR. `ON CONFLICT DO UPDATE` bunu veritabani
# seviyesinde atomik cozuyor.
#
# `amount_ml = water_logs.amount_ml + EXCLUDED.amount_ml`: EKLEME, uzerine yazma
# degil. Kullanici gun icinde birden cok kez su ekliyor.
ADD_AMOUNT = """
INSERT INTO water_logs (user_id, log_date, amount_ml)
VALUES ($1, $2, $3)
ON CONFLICT (user_id, log_date) DO UPDATE
   SET amount_ml = LEAST(water_logs.amount_ml + EXCLUDED.amount_ml, 20000),
       updated_at = now()
RETURNING log_date, amount_ml
"""

# Dogrudan ayarlama — kullanici sayiyi elle duzeltmek istediginde.
SET_AMOUNT = """
INSERT INTO water_logs (user_id, log_date, amount_ml)
VALUES ($1, $2, $3)
ON CONFLICT (user_id, log_date) DO UPDATE
   SET amount_ml = EXCLUDED.amount_ml,
       updated_at = now()
RETURNING log_date, amount_ml
"""

DELETE_BY_USER = "DELETE FROM water_logs WHERE user_id = $1"


@dataclass(frozen=True)
class WaterRow:
    log_date: date
    amount_ml: int


async def fetch_day(
    conn: asyncpg.Connection, user_id: uuid.UUID, day: date
) -> WaterRow | None:
    row = await conn.fetchrow(SELECT_DAY, user_id, day)
    if row is None:
        return None
    return WaterRow(log_date=row["log_date"], amount_ml=row["amount_ml"])


async def fetch_range(
    conn: asyncpg.Connection, user_id: uuid.UUID, start: date, end: date
) -> list[WaterRow]:
    rows = await conn.fetch(SELECT_RANGE, user_id, start, end)
    return [
        WaterRow(log_date=row["log_date"], amount_ml=row["amount_ml"]) for row in rows
    ]


async def add(
    conn: asyncpg.Connection, user_id: uuid.UUID, day: date, amount_ml: int
) -> WaterRow:
    """Gunun toplamina EKLER. Ust sinir veritabani tarafinda kirpiliyor."""
    row = await conn.fetchrow(ADD_AMOUNT, user_id, day, amount_ml)
    return WaterRow(log_date=row["log_date"], amount_ml=row["amount_ml"])


async def set_amount(
    conn: asyncpg.Connection, user_id: uuid.UUID, day: date, amount_ml: int
) -> WaterRow:
    """Gunun toplamini DOGRUDAN ayarlar (duzeltme icin)."""
    row = await conn.fetchrow(SET_AMOUNT, user_id, day, amount_ml)
    return WaterRow(log_date=row["log_date"], amount_ml=row["amount_ml"])


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])
