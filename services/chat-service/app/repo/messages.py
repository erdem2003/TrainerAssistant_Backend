"""messages SQL — idempotent yazım (workout-service'in 201/200/409 merdiveni
ile aynı desen) ve sayfalı okuma (ADR 0014, Faz S6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_FIND_BY_ID = """
SELECT id, conversation_id, seq, sender_id, body, content_hash, redacted_at, created_at
  FROM messages WHERE id = $1
"""

# ★ SEQ ATAMASI ATOMİK ★ `next_seq - 1` döndürülüp aynı transaction'da
# `messages`'a yazılıyor — iki eşzamanlı gönderim satır kilidiyle sıraya
# giriyor, iki mesaj asla aynı `seq`'i almıyor.
_ASSIGN_SEQ = """
UPDATE conversations SET next_seq = next_seq + 1 WHERE id = $1 RETURNING next_seq - 1
"""

_INSERT_MESSAGE = """
INSERT INTO messages (id, conversation_id, seq, sender_id, body, content_hash)
VALUES ($1, $2, $3, $4, $5, $6)
"""

_SELECT_PAGE = """
SELECT id, conversation_id, seq, sender_id, body, content_hash, redacted_at, created_at
  FROM messages
 WHERE conversation_id = $1 AND seq < $2
 ORDER BY seq DESC
 LIMIT $3
"""

_REDACT_BY_SENDER = """
UPDATE messages SET body = NULL, redacted_at = now()
 WHERE sender_id = $1 AND redacted_at IS NULL
"""


@dataclass(frozen=True)
class Message:
    id: uuid.UUID
    conversation_id: uuid.UUID
    seq: int
    sender_id: uuid.UUID
    body: str | None
    content_hash: str
    redacted_at: datetime | None
    created_at: datetime


async def find_by_id(conn: asyncpg.Connection, message_id: uuid.UUID) -> Message | None:
    row = await conn.fetchrow(_FIND_BY_ID, message_id)
    return Message(**dict(row)) if row else None


async def insert(
    conn: asyncpg.Connection,
    *,
    message_id: uuid.UUID,
    conversation_id: uuid.UUID,
    sender_id: uuid.UUID,
    body: str,
    content_hash: str,
) -> Message:
    seq = await conn.fetchval(_ASSIGN_SEQ, conversation_id)
    await conn.execute(_INSERT_MESSAGE, message_id, conversation_id, seq, sender_id, body, content_hash)
    return await find_by_id(conn, message_id)


async def fetch_page(
    conn: asyncpg.Connection, conversation_id: uuid.UUID, before_seq: int, limit: int
) -> list[Message]:
    rows = await conn.fetch(_SELECT_PAGE, conversation_id, before_seq, limit)
    # DESC sorgulandı (en yeniden geriye) ama görüntüleme ASC beklenir —
    # istemci tarafında ayrıca ters çevirmeyi unutmamak yerine burada yapılır.
    return [Message(**dict(r)) for r in reversed(rows)]


async def redact_by_sender(conn: asyncpg.Connection, sender_id: uuid.UUID) -> int:
    result = await conn.execute(_REDACT_BY_SENDER, sender_id)
    return int(result.rsplit(" ", 1)[1])
