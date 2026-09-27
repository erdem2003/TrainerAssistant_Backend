"""Arkadaslik — tek kanonik satir (user_low, user_high), iki ayri istek/kabul
satiri DEGIL. Gerekce: ADR 0014 "Sonuclar" bolumu.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import asyncpg


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Kanonik siralama: PRIMARY KEY (user_low, user_high) CHECK (user_low < user_high)."""
    return (a, b) if str(a) < str(b) else (b, a)


# ★ TEK UPSERT, IKI SENARYOYU BIRDEN COZUYOR ★
# Satir yoksa PENDING olarak eklenir. Satir zaten PENDING ve FARKLI kisi
# tarafindan istenmisse (karsilikli istek) ACCEPTED'e ceviriyoruz — iki taraf
# da zaten istemis demektir. Bu, ayni anda iki istek atildiginda dahi TEK bir
# satirla ve satir kilidiyle atomik olarak cozuluyor (ADR 0014, Sonuclar —
# "aynı anda karşılıklı istek atılırsa... sonuç otomatik kabul olur").
_UPSERT_REQUEST = """
INSERT INTO friendships (user_low, user_high, status, requested_by)
VALUES ($1, $2, 'PENDING', $3)
ON CONFLICT (user_low, user_high) DO UPDATE SET
    status = CASE
        WHEN friendships.status = 'PENDING' AND friendships.requested_by != $3
            THEN 'ACCEPTED'
        ELSE friendships.status
    END,
    updated_at = now()
RETURNING status, requested_by
"""

_ACCEPT = """
UPDATE friendships
   SET status = 'ACCEPTED', updated_at = now()
 WHERE user_low = $1 AND user_high = $2
   AND status = 'PENDING' AND requested_by != $3
RETURNING status
"""

_REJECT_OR_UNFRIEND = """
DELETE FROM friendships WHERE user_low = $1 AND user_high = $2
"""

_LIST_FRIENDS = """
SELECT CASE WHEN user_low = $1 THEN user_high ELSE user_low END AS friend_id,
       created_at
  FROM friendships
 WHERE (user_low = $1 OR user_high = $1) AND status = 'ACCEPTED'
 ORDER BY created_at DESC
"""

_LIST_PENDING_INCOMING = """
SELECT CASE WHEN user_low = $1 THEN user_high ELSE user_low END AS requester_id,
       created_at
  FROM friendships
 WHERE (user_low = $1 OR user_high = $1) AND status = 'PENDING' AND requested_by != $1
 ORDER BY created_at DESC
"""

_LIST_PENDING_OUTGOING = """
SELECT CASE WHEN user_low = $1 THEN user_high ELSE user_low END AS addressee_id,
       created_at
  FROM friendships
 WHERE (user_low = $1 OR user_high = $1) AND status = 'PENDING' AND requested_by = $1
 ORDER BY created_at DESC
"""

_ARE_FRIENDS = """
SELECT 1 FROM friendships
 WHERE user_low = $1 AND user_high = $2 AND status = 'ACCEPTED'
"""

_DELETE_ALL_FOR_USER = """
DELETE FROM friendships WHERE user_low = $1 OR user_high = $1
"""


@dataclass(frozen=True)
class RequestResult:
    status: str
    requested_by: uuid.UUID


async def send_request(
    conn: asyncpg.Connection, requester: uuid.UUID, addressee: uuid.UUID
) -> RequestResult:
    low, high = _pair(requester, addressee)
    row = await conn.fetchrow(_UPSERT_REQUEST, low, high, requester)
    return RequestResult(status=row["status"], requested_by=row["requested_by"])


async def accept(conn: asyncpg.Connection, me: uuid.UUID, requester_id: uuid.UUID) -> bool:
    low, high = _pair(me, requester_id)
    row = await conn.fetchrow(_ACCEPT, low, high, me)
    return row is not None


async def reject_or_unfriend(conn: asyncpg.Connection, a: uuid.UUID, b: uuid.UUID) -> None:
    low, high = _pair(a, b)
    await conn.execute(_REJECT_OR_UNFRIEND, low, high)


async def list_friends(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[dict]:
    rows = await conn.fetch(_LIST_FRIENDS, user_id)
    return [dict(r) for r in rows]


async def list_pending_incoming(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[dict]:
    rows = await conn.fetch(_LIST_PENDING_INCOMING, user_id)
    return [dict(r) for r in rows]


async def list_pending_outgoing(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[dict]:
    rows = await conn.fetch(_LIST_PENDING_OUTGOING, user_id)
    return [dict(r) for r in rows]


async def are_friends(conn: asyncpg.Connection, a: uuid.UUID, b: uuid.UUID) -> bool:
    low, high = _pair(a, b)
    row = await conn.fetchrow(_ARE_FRIENDS, low, high)
    return row is not None


async def delete_all_for_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    result = await conn.execute(_DELETE_ALL_FOR_USER, user_id)
    return int(result.split()[-1])
