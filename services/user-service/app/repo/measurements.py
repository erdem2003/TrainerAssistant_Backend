"""body_measurements tablosunun SQL'i — vücut ölçüsü zaman serisi (B6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import asyncpg

SELECT_RANGE = """
SELECT measured_date, weight_kg, waist_cm, arm_cm FROM body_measurements
 WHERE user_id = $1 AND measured_date BETWEEN $2 AND $3
 ORDER BY measured_date
"""

# UPSERT — su_takibi ile ayni desen. COALESCE ile alan bazinda birlestirme:
# kullanici sabah kiloyu, aksam beli girerse ikinci yazim ilkini SILMEMELI.
UPSERT = """
INSERT INTO body_measurements (user_id, measured_date, weight_kg, waist_cm, arm_cm)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (user_id, measured_date) DO UPDATE
   SET weight_kg = COALESCE(EXCLUDED.weight_kg, body_measurements.weight_kg),
       waist_cm  = COALESCE(EXCLUDED.waist_cm,  body_measurements.waist_cm),
       arm_cm    = COALESCE(EXCLUDED.arm_cm,    body_measurements.arm_cm),
       updated_at = now()
RETURNING measured_date, weight_kg, waist_cm, arm_cm
"""

DELETE_BY_USER = "DELETE FROM body_measurements WHERE user_id = $1"


@dataclass(frozen=True)
class MeasurementRow:
    measured_date: date
    weight_kg: float | None
    waist_cm: float | None
    arm_cm: float | None


async def upsert(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    day: date,
    weight_kg: float | None,
    waist_cm: float | None,
    arm_cm: float | None,
) -> MeasurementRow:
    row = await conn.fetchrow(UPSERT, user_id, day, weight_kg, waist_cm, arm_cm)
    return MeasurementRow(
        measured_date=row["measured_date"],
        weight_kg=row["weight_kg"],
        waist_cm=row["waist_cm"],
        arm_cm=row["arm_cm"],
    )


async def fetch_range(
    conn: asyncpg.Connection, user_id: uuid.UUID, start: date, end: date
) -> list[MeasurementRow]:
    rows = await conn.fetch(SELECT_RANGE, user_id, start, end)
    return [
        MeasurementRow(
            measured_date=row["measured_date"],
            weight_kg=row["weight_kg"],
            waist_cm=row["waist_cm"],
            arm_cm=row["arm_cm"],
        )
        for row in rows
    ]


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])
