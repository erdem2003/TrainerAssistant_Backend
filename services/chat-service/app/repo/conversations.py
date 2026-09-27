"""conversations / conversation_participants SQL (ADR 0014, Faz S6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """`friendships._pair` ile aynı kanonik sıralama — bkz. social-service."""
    return (a, b) if str(a) < str(b) else (b, a)


_FIND_BY_PAIR = "SELECT id FROM conversations WHERE user_low = $1 AND user_high = $2"

_INSERT_CONVERSATION = """
INSERT INTO conversations (id, user_low, user_high) VALUES ($1, $2, $3)
ON CONFLICT (user_low, user_high) DO NOTHING
RETURNING id
"""

_INSERT_PARTICIPANT = """
INSERT INTO conversation_participants (conversation_id, user_id) VALUES ($1, $2)
ON CONFLICT (conversation_id, user_id) DO NOTHING
"""

_FIND_PARTICIPANT = """
SELECT last_read_seq, left_at FROM conversation_participants
 WHERE conversation_id = $1 AND user_id = $2
"""

_FIND_PEER = """
SELECT user_id FROM conversation_participants
 WHERE conversation_id = $1 AND user_id != $2
"""

_MARK_READ = """
UPDATE conversation_participants
   SET last_read_seq = GREATEST(last_read_seq, $3), last_read_at = now()
 WHERE conversation_id = $1 AND user_id = $2
"""

# Faz S10: hesap silindiğinde satır SİLİNMEZ — `last_read_seq`/geçmiş
# karşı tarafın konuşma listesinde kalmalı (ADR 0014 Sonuçlar, "sohbet hâlâ
# okunabilir"). Yalnızca `left_at` damgalanır.
_MARK_LEFT_ALL = """
UPDATE conversation_participants SET left_at = now()
 WHERE user_id = $1 AND left_at IS NULL
"""

# ★ LİSTE SORGUSU ★ Konuşma başına: karşı taraf, son mesaj önizlemesi,
# okunmamış sayısı — hepsi TEK sorguda, `LATERAL` ile son mesaja bakılıyor.
_SELECT_FOR_USER = """
SELECT c.id AS conversation_id,
       cp_peer.user_id AS peer_id,
       cp_me.last_read_seq AS my_last_read_seq,
       c.next_seq - 1 AS max_seq,
       last_msg.body AS last_body,
       last_msg.sender_id AS last_sender_id,
       last_msg.created_at AS last_created_at,
       last_msg.redacted_at AS last_redacted_at
  FROM conversation_participants cp_me
  JOIN conversations c ON c.id = cp_me.conversation_id
  JOIN conversation_participants cp_peer
    ON cp_peer.conversation_id = c.id AND cp_peer.user_id != cp_me.user_id
  LEFT JOIN LATERAL (
      SELECT body, sender_id, created_at, redacted_at
        FROM messages m
       WHERE m.conversation_id = c.id
       ORDER BY m.seq DESC
       LIMIT 1
  ) last_msg ON true
 WHERE cp_me.user_id = $1
 ORDER BY COALESCE(last_msg.created_at, c.created_at) DESC
"""


@dataclass(frozen=True)
class ConversationSummary:
    conversation_id: uuid.UUID
    peer_id: uuid.UUID
    unread_count: int
    last_body: str | None
    last_sender_id: uuid.UUID | None
    last_created_at: datetime | None
    last_redacted_at: datetime | None


async def get_or_create(conn: asyncpg.Connection, user_a: uuid.UUID, user_b: uuid.UUID) -> uuid.UUID:
    low, high = _pair(user_a, user_b)

    existing = await conn.fetchrow(_FIND_BY_PAIR, low, high)
    if existing is not None:
        return existing["id"]

    new_id = uuid.uuid4()
    row = await conn.fetchrow(_INSERT_CONVERSATION, new_id, low, high)
    # ON CONFLICT DO NOTHING + RETURNING: eşzamanlı iki istek aynı anda ilk
    # kayıt için yarışırsa biri RETURNING alır, diğeri None görür — o zaman
    # zaten oluşmuş satırı tekrar okur (kayıp yok, çift satır da yok).
    conversation_id = row["id"] if row is not None else (await conn.fetchrow(_FIND_BY_PAIR, low, high))["id"]

    await conn.execute(_INSERT_PARTICIPANT, conversation_id, user_a)
    await conn.execute(_INSERT_PARTICIPANT, conversation_id, user_b)
    return conversation_id


async def find_participant(conn: asyncpg.Connection, conversation_id: uuid.UUID, user_id: uuid.UUID):
    return await conn.fetchrow(_FIND_PARTICIPANT, conversation_id, user_id)


async def find_peer(conn: asyncpg.Connection, conversation_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID | None:
    row = await conn.fetchrow(_FIND_PEER, conversation_id, user_id)
    return row["user_id"] if row else None


async def mark_read(conn: asyncpg.Connection, conversation_id: uuid.UUID, user_id: uuid.UUID, up_to_seq: int) -> None:
    await conn.execute(_MARK_READ, conversation_id, user_id, up_to_seq)


async def mark_left_all(conn: asyncpg.Connection, user_id: uuid.UUID) -> None:
    await conn.execute(_MARK_LEFT_ALL, user_id)


async def list_for_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[ConversationSummary]:
    rows = await conn.fetch(_SELECT_FOR_USER, user_id)
    return [
        ConversationSummary(
            conversation_id=r["conversation_id"],
            peer_id=r["peer_id"],
            unread_count=max(0, r["max_seq"] - r["my_last_read_seq"]),
            last_body=r["last_body"],
            last_sender_id=r["last_sender_id"],
            last_created_at=r["last_created_at"],
            last_redacted_at=r["last_redacted_at"],
        )
        for r in rows
    ]
