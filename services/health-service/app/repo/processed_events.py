"""Islenmis event kaydi — ayni event iki kez islenmesin (idempotent consumer)."""

from __future__ import annotations

import uuid

import asyncpg

_CLAIM = """
INSERT INTO processed_events (event_id, event_type)
VALUES ($1, $2)
ON CONFLICT (event_id) DO NOTHING
"""


async def claim(
    conn: asyncpg.Connection,
    event_id: uuid.UUID,
    event_type: str,
) -> bool:
    """Event'i ilk kez görüyorsak `True`, tekrarsa `False`."""
    result = await conn.execute(_CLAIM, event_id, event_type)
    return result != "INSERT 0 0"
