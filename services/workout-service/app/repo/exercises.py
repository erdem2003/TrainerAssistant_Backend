"""exercises tablosunun SQL'i — egzersiz katalogu (ADR 0005: ayri servis degil)."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

SELECT_ALL = """
SELECT id, display_name, required_view FROM exercises ORDER BY display_name
"""

EXISTS = "SELECT 1 FROM exercises WHERE id = $1"


@dataclass(frozen=True)
class Exercise:
    id: str
    display_name: str
    required_view: str


async def list_all(conn: asyncpg.Connection) -> list[Exercise]:
    rows = await conn.fetch(SELECT_ALL)
    return [
        Exercise(
            id=row["id"],
            display_name=row["display_name"],
            required_view=row["required_view"],
        )
        for row in rows
    ]


async def exists(conn: asyncpg.Connection, exercise_id: str) -> bool:
    return await conn.fetchval(EXISTS, exercise_id) is not None
