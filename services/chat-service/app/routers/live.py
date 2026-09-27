"""Canlı ortak antrenman — saf röle, kalıcı veri yok (ADR 0014, Faz S7).

TEK DOĞRULUK KAYNAĞI: `app/schemas.py`'deki "Canlı ortak antrenman" bölümü —
`session_id`'nin neden bir yetki tablosu gerektirmediğinin gerekçesi orada.

Bu router `messages`/`conversations` tablolarına HİÇ dokunmaz: `hub.publish()`
çağıran ince bir katman. Yazma (rep sayısı ilerlemesi) burada, alma karşı
tarafın soketinde (`app/routers/realtime.py`) — sohbetle AYNI ADR 0014 kuralı
("soket yalnızca alıcıdır").
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, status

from app import social_client
from app.errors import not_found, unprocessable
from app.hub import hub
from app.identity import require_user_id
from app.schemas import LiveActionIn, LiveInviteIn, LiveInviteOut, LiveProgressIn

router = APIRouter(prefix="/v1/chat/live", tags=["live"])


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise unprocessable(f"{field} geçerli bir UUID değil") from None


@router.post("/invite", response_model=LiveInviteOut, status_code=status.HTTP_201_CREATED)
async def invite(body: LiveInviteIn, x_user_id: str | None = Header(default=None)) -> LiveInviteOut:
    me = require_user_id(x_user_id)
    peer_id = _parse_uuid(body.peer_user_id, "peer_user_id")

    if peer_id == me:
        raise unprocessable("kendine davet gönderemezsin")

    # ★ TEK YETKİ KONTROLÜ BURADA ★ join/progress/end bu kontrolü TEKRARLAMAZ —
    # session_id zaten yalnızca davet edilen tarafa (arkadaşlık doğrulanmış
    # şekilde) ulaşan bir jeton.
    if not await social_client.are_friends(me, peer_id):
        raise not_found("Kullanıcı bulunamadı")

    session_id = uuid.uuid4()
    await hub.publish(
        peer_id,
        {
            "type": "SESSION_INVITE",
            "session_id": str(session_id),
            "from_user_id": str(me),
            "exercise_id": body.exercise_id,
        },
    )
    return LiveInviteOut(session_id=str(session_id))


@router.post("/{session_id}/join", status_code=status.HTTP_204_NO_CONTENT)
async def join(session_id: str, body: LiveActionIn, x_user_id: str | None = Header(default=None)) -> None:
    me = require_user_id(x_user_id)
    peer_id = _parse_uuid(body.peer_user_id, "peer_user_id")
    sid = _parse_uuid(session_id, "session_id")

    await hub.publish(
        peer_id,
        {"type": "SESSION_JOINED", "session_id": str(sid), "from_user_id": str(me)},
    )


@router.post("/{session_id}/progress", status_code=status.HTTP_204_NO_CONTENT)
async def progress(session_id: str, body: LiveProgressIn, x_user_id: str | None = Header(default=None)) -> None:
    me = require_user_id(x_user_id)
    peer_id = _parse_uuid(body.peer_user_id, "peer_user_id")
    sid = _parse_uuid(session_id, "session_id")

    await hub.publish(
        peer_id,
        {"type": "SESSION_PROGRESS", "session_id": str(sid), "from_user_id": str(me), "reps": body.reps},
    )


@router.post("/{session_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end(session_id: str, body: LiveActionIn, x_user_id: str | None = Header(default=None)) -> None:
    me = require_user_id(x_user_id)
    peer_id = _parse_uuid(body.peer_user_id, "peer_user_id")
    sid = _parse_uuid(session_id, "session_id")

    await hub.publish(
        peer_id,
        {"type": "SESSION_ENDED", "session_id": str(sid), "from_user_id": str(me)},
    )
