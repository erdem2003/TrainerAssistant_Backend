"""GET /v1/social/notifications, POST .../read (ADR 0014, Faz S8).

Üretim (satır yazımı) `friendships.py`/`posts.py` router'larında — bu dosya
yalnızca okuma ve okundu işaretleme.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Query, status

from app.db import db
from app.errors import unprocessable
from app.identity import require_user_id
from app.repo import notifications
from app.schemas import NotificationActorOut, NotificationOut, NotificationPage

router = APIRouter(prefix="/v1/social/notifications", tags=["notifications"])

_LIMIT_DEFAULT = 30
_LIMIT_MAX = 100


def _epoch_ms(dt) -> int:
    return int(dt.timestamp() * 1000)


def _decode_cursor(cursor: str | None) -> datetime:
    if cursor is None:
        return datetime.now(tz=timezone.utc)
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return datetime.fromtimestamp(float(base64.urlsafe_b64decode(padded).decode()), tz=timezone.utc)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise unprocessable("Sayfalama imleci geçersiz") from None


def _encode_cursor(dt: datetime) -> str:
    return base64.urlsafe_b64encode(str(dt.timestamp()).encode()).decode().rstrip("=")


@router.get("", response_model=NotificationPage)
async def list_notifications(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=_LIMIT_DEFAULT, le=_LIMIT_MAX),
    x_user_id: str | None = Header(default=None),
) -> NotificationPage:
    user_id = require_user_id(x_user_id)
    before = _decode_cursor(cursor)

    async with db.pool.acquire() as conn:
        rows = await notifications.fetch_page(conn, user_id, before, limit + 1)
        unread = await notifications.count_unread(conn, user_id)

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        NotificationOut(
            id=str(r["id"]),
            type=r["type"],
            actor=NotificationActorOut(
                user_id=str(r["actor_id"]),
                username=r["actor_username"],
                display_name=r["actor_display_name"],
                avatar_seed=r["actor_avatar_seed"],
            ),
            subject_id=str(r["subject_id"]),
            created_at=_epoch_ms(r["created_at"]),
            read=r["read_at"] is not None,
        )
        for r in rows
    ]

    next_cursor = _encode_cursor(rows[-1]["created_at"]) if has_more and rows else None
    return NotificationPage(items=items, unread_count=unread, next_cursor=next_cursor)


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(x_user_id: str | None = Header(default=None)) -> None:
    """Tümünü okundu işaretler — v1 kapsamı tekil bildirim seçimini
    desteklemiyor (bildirim listesi ekranı açıldığında tek çağrı yeterli)."""
    user_id = require_user_id(x_user_id)

    async with db.pool.acquire() as conn:
        await notifications.mark_all_read(conn, user_id)
