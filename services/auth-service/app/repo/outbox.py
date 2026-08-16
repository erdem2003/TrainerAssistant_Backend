"""outbox tablosunun SQL'i."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import asyncpg

# ---------------------------------------------------------------------------

ENQUEUE = """
INSERT INTO outbox (event_type, topic, partition_key, payload)
VALUES ($1, $2, $3, $4::jsonb)
RETURNING id
"""

# Worker'ın aldığı toplu iş.
CLAIM_BATCH = """
SELECT id, event_type, topic, partition_key, payload, created_at, attempts
  FROM outbox
 WHERE published_at IS NULL
   AND attempts < $2
 ORDER BY created_at
 LIMIT $1
   FOR UPDATE SKIP LOCKED
"""

MARK_PUBLISHED = """
UPDATE outbox
   SET published_at = now()
 WHERE id = $1
"""

# Başarısızlıkta satır SİLİNMEZ, sayaç artar. Böylece hem yeniden denenir hem de
# neden başarısız olduğu görülebilir. `attempts` tavana ulaşınca satır artık
# alınmaz — sonsuz döngüye girmemesi için.
MARK_FAILED = """
UPDATE outbox
   SET attempts   = attempts + 1,
       last_error = $2
 WHERE id = $1
"""

# ---------------------------------------------------------------------------


async def enqueue(
    conn: asyncpg.Connection,
    event_type: str,
    topic: str,
    partition_key: str,
    payload: dict,
) -> uuid.UUID:
    """Çağıran taraf transaction AÇMIŞ olmalı — outbox'ın tüm anlamı bu."""
    return await conn.fetchval(
        ENQUEUE, event_type, topic, partition_key, json.dumps(payload)
    )


class OutboxRow:
    __slots__ = ("id", "event_type", "topic", "partition_key", "payload",
                 "created_at", "attempts")

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: uuid.UUID = row["id"]
        self.event_type: str = row["event_type"]
        self.topic: str = row["topic"]
        self.partition_key: str = row["partition_key"]
        self.payload: dict = json.loads(row["payload"])
        self.created_at: datetime = row["created_at"]
        self.attempts: int = row["attempts"]


async def claim_batch(
    conn: asyncpg.Connection, limit: int, max_attempts: int
) -> list[OutboxRow]:
    rows = await conn.fetch(CLAIM_BATCH, limit, max_attempts)
    return [OutboxRow(row) for row in rows]


async def mark_published(conn: asyncpg.Connection, row_id: uuid.UUID) -> None:
    await conn.execute(MARK_PUBLISHED, row_id)


async def mark_failed(conn: asyncpg.Connection, row_id: uuid.UUID, error: str) -> None:
    await conn.execute(MARK_FAILED, row_id, error[:500])
