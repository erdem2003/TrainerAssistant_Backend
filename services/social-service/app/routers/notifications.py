"""GET /v1/social/notifications, POST .../read (ADR 0014, Faz S8).

Üretim (doküman yazımı) `friendships.py`/`posts.py`/`challenges.py`
router'larında — bu dosya yalnızca okuma ve okundu işaretleme. Mobil aynı
alt koleksiyonu (`social_users/{uid}/notifications`) Firestore dinleyicisiyle
de izleyebiliyor; bu uç sayfalı geçmiş ve okunmamış sayısı için duruyor.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Query, status

from app.errors import unprocessable
from app.identity import require_user_id
from app.repo import notifications, profiles
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

    rows = await notifications.fetch_page(user_id, before, limit + 1)
    unread = await notifications.count_unread(user_id)

    has_more = len(rows) > limit
    rows = rows[:limit]

    # LEFT JOIN semantiği: silinmiş aktör "Silinmiş kullanıcı" olarak (alanlar
    # boş) gösteriliyor — `NotificationActorOut`'un alanları opsiyonel.
    actors = await profiles.profiles_map(uuid.UUID(r["actor_id"]) for r in rows)

    items = []
    for r in rows:
        actor = actors.get(uuid.UUID(r["actor_id"]))
        items.append(
            NotificationOut(
                id=r["id"],
                type=r["type"],
                actor=NotificationActorOut(
                    user_id=r["actor_id"],
                    username=actor.username if actor else None,
                    display_name=actor.display_name if actor else None,
                    avatar_seed=actor.avatar_seed if actor else None,
                ),
                subject_id=r["subject_id"],
                created_at=_epoch_ms(r["created_at"]),
                read=r.get("read_at") is not None,
            )
        )

    next_cursor = _encode_cursor(rows[-1]["created_at"]) if has_more and rows else None
    return NotificationPage(items=items, unread_count=unread, next_cursor=next_cursor)


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(x_user_id: str | None = Header(default=None)) -> None:
    """Tümünü okundu işaretler — v1 kapsamı tekil bildirim seçimini
    desteklemiyor (bildirim listesi ekranı açıldığında tek çağrı yeterli)."""
    user_id = require_user_id(x_user_id)

    await notifications.mark_all_read(user_id)
