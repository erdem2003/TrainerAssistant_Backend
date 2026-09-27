"""notifications SQL (ADR 0014, Faz S8) — doğal anahtar + UPSERT.

`app.notify.publish_notification` bu modülden ÇAĞRILMAZ: satır yazımı ve
Redis uyandırma sinyali ayrı adımlar (router transaction'ı commit ettikten
SONRA yayınlanır) — sebep `app/notify.py`'de.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

# ON CONFLICT DO UPDATE: ayni eylem TEKRARLANDIGINDA (begen->kaldir->begen)
# TEK satir kalir, created_at guncellenir, read_at SIFIRLANIR — kullanici
# onceden okumus olsa bile bu YENI bir olay, tekrar "okunmamis" gorunmeli.
_UPSERT = """
INSERT INTO notifications (id, recipient_id, type, actor_id, subject_id)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (recipient_id, type, actor_id, subject_id)
DO UPDATE SET created_at = now(), read_at = NULL
RETURNING id, created_at
"""

_SELECT_PAGE = """
SELECT n.id, n.type, n.actor_id, n.subject_id, n.created_at, n.read_at,
       p.username AS actor_username, p.display_name AS actor_display_name,
       p.avatar_seed AS actor_avatar_seed
  FROM notifications n
  LEFT JOIN social_profiles p ON p.user_id = n.actor_id
 WHERE n.recipient_id = $1 AND n.created_at < $2
 ORDER BY n.created_at DESC
 LIMIT $3
"""

_COUNT_UNREAD = "SELECT COUNT(*) FROM notifications WHERE recipient_id = $1 AND read_at IS NULL"

_MARK_ALL_READ = """
UPDATE notifications SET read_at = now() WHERE recipient_id = $1 AND read_at IS NULL
"""

_DELETE_BY_RECIPIENT = "DELETE FROM notifications WHERE recipient_id = $1"


@dataclass(frozen=True)
class UpsertResult:
    id: uuid.UUID
    created_at: datetime


async def upsert(
    conn: asyncpg.Connection,
    *,
    notification_id: uuid.UUID,
    recipient_id: uuid.UUID,
    notification_type: str,
    actor_id: uuid.UUID,
    subject_id: uuid.UUID,
) -> UpsertResult:
    row = await conn.fetchrow(_UPSERT, notification_id, recipient_id, notification_type, actor_id, subject_id)
    return UpsertResult(id=row["id"], created_at=row["created_at"])


async def fetch_page(
    conn: asyncpg.Connection, recipient_id: uuid.UUID, before: datetime, limit: int
) -> list[asyncpg.Record]:
    return await conn.fetch(_SELECT_PAGE, recipient_id, before, limit)


async def count_unread(conn: asyncpg.Connection, recipient_id: uuid.UUID) -> int:
    return await conn.fetchval(_COUNT_UNREAD, recipient_id)


async def mark_all_read(conn: asyncpg.Connection, recipient_id: uuid.UUID) -> None:
    await conn.execute(_MARK_ALL_READ, recipient_id)


async def delete_by_recipient(conn: asyncpg.Connection, recipient_id: uuid.UUID) -> None:
    await conn.execute(_DELETE_BY_RECIPIENT, recipient_id)
