"""Konuşma listesi, mesaj gönderme/okuma, okundu işaretleme (ADR 0014, Faz S6).

Yazma HER ZAMAN buradan (HTTP). Okuma iki yoldan: bu uçlar (sayfalı geçmiş,
liste) ve mobilin Firestore dinleyicisi (`chat_conversations/{id}` +
`messages` alt koleksiyonu — ADR 0019 karar 5). Redis/WebSocket üzerinden
MESSAGE/RECEIPT çerçevesi artık gönderilmiyor: yazılan doküman sinyalin kendisi.

Arkadaşlık/profil social-service'te yaşadığı için yazma yetkisi ve görüntü
verisi `app/social_client.py` üzerinden geliyor (ADR 0005'in izin verdiği
minimum senkron istisna).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query, Response, status
from nabiz_firebase import push_client

from app import social_client
from app.errors import conflict, not_found, unprocessable
from app.identity import require_user_id
from app.repo import conversations, messages
from app.schemas import (
    ConversationCreateIn,
    ConversationListOut,
    ConversationOut,
    MarkReadIn,
    MessageIn,
    MessageOut,
    MessagePage,
    PeerOut,
)

router = APIRouter(prefix="/v1/chat", tags=["chat"])

_MESSAGES_LIMIT_DEFAULT = 30
_MESSAGES_LIMIT_MAX = 100

_UNKNOWN_PEER = PeerOut(user_id="", username="", display_name="Bilinmeyen kullanıcı", avatar_seed="")


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise unprocessable(f"'{value}' geçerli bir UUID değil") from None


def _epoch_ms(dt) -> int | None:
    return int(dt.timestamp() * 1000) if dt is not None else None


async def _require_participant(conversation_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    conversation = await conversations.find(conversation_id)
    if not conversations.is_participant(conversation, user_id):
        raise not_found("Konuşma bulunamadı")
    return conversation


def _peer_out(profile: social_client.ProfileSummary | None) -> PeerOut:
    if profile is None:
        return _UNKNOWN_PEER
    return PeerOut(
        user_id=profile.user_id,
        username=profile.username,
        display_name=profile.display_name,
        avatar_seed=profile.avatar_seed,
    )


def _message_to_out(m: messages.Message) -> MessageOut:
    return MessageOut(
        id=str(m.id),
        conversation_id=str(m.conversation_id),
        seq=m.seq,
        sender_id=str(m.sender_id),
        body=None if m.redacted_at is not None else m.body,
        redacted=m.redacted_at is not None,
        created_at=_epoch_ms(m.created_at),
    )


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreateIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> ConversationOut:
    me = require_user_id(x_user_id)
    peer_id = _parse_uuid(body.peer_user_id)
    if peer_id == me:
        raise unprocessable("kendinle konuşma açamazsın")

    if not await social_client.are_friends(me, peer_id):
        raise not_found("Kullanıcı bulunamadı")

    conversation_id = await conversations.get_or_create(me, peer_id)

    profiles = await social_client.fetch_profiles([peer_id])
    peer_profile = profiles.get(str(peer_id))

    response.status_code = status.HTTP_200_OK  # get-or-create: her zaman idempotent 200 anlamına gelir
    return ConversationOut(
        id=str(conversation_id),
        peer=_peer_out(peer_profile),
        unread_count=0,
        last_message=None,
        last_message_from_me=False,
        last_message_redacted=False,
        last_message_at=None,
    )


@router.get("/conversations", response_model=ConversationListOut)
async def list_conversations(x_user_id: str | None = Header(default=None)) -> ConversationListOut:
    me = require_user_id(x_user_id)

    rows = await conversations.list_for_user(me)

    profiles = await social_client.fetch_profiles([r.peer_id for r in rows])

    items = []
    for r in rows:
        peer_profile = profiles.get(str(r.peer_id))
        items.append(
            ConversationOut(
                id=str(r.conversation_id),
                peer=_peer_out(peer_profile),
                unread_count=r.unread_count,
                last_message=None if r.last_redacted else r.last_body,
                last_message_from_me=(r.last_sender_id == me) if r.last_sender_id else False,
                last_message_redacted=r.last_redacted,
                last_message_at=_epoch_ms(r.last_created_at),
            )
        )

    return ConversationListOut(items=items)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: str,
    before_seq: int | None = Query(default=None),
    limit: int = Query(default=_MESSAGES_LIMIT_DEFAULT, le=_MESSAGES_LIMIT_MAX),
    x_user_id: str | None = Header(default=None),
) -> MessagePage:
    me = require_user_id(x_user_id)
    cid = _parse_uuid(conversation_id)
    cursor = before_seq if before_seq is not None else 2**31 - 1

    await _require_participant(cid, me)
    page = await messages.fetch_page(cid, cursor, limit + 1)

    # DESC sorgulanıp ASC'e çevrildiği için "daha eski var mı" en BAŞTAKİ
    # (en eski) satırın fazlalık olup olmadığına bakılarak anlaşılır.
    has_more = len(page) > limit
    if has_more:
        page = page[1:]
    next_before_seq = page[0].seq if has_more and page else None

    return MessagePage(items=[_message_to_out(m) for m in page], next_before_seq=next_before_seq)


@router.post(
    "/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
async def send_message(
    conversation_id: str,
    body: MessageIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> MessageOut:
    """service-contract §4: 201 ilk yazım, 200 aynı id+içerik, 409 aynı id
    farklı içerik. Arkadaşlık bozulmuşsa (salt-okunur kural, ADR 0014
    Sonuçlar) gönderme 422 ile reddedilir — geçmişin OKUNMASI etkilenmez."""
    sender_id = require_user_id(x_user_id)
    cid = _parse_uuid(conversation_id)
    message_id = _parse_uuid(body.id)
    incoming_hash = body.content_hash()

    conversation = await _require_participant(cid, sender_id)

    existing = await messages.find_by_id(cid, message_id)
    if existing is None:
        peer_id = conversations.peer_of(conversation, sender_id)
        if peer_id is None:
            raise not_found("Konuşma bulunamadı")
        if not await social_client.are_friends(sender_id, peer_id):
            raise unprocessable("Artık arkadaş değilsiniz, mesaj gönderemezsin")
        message, created = await messages.insert(
            message_id=message_id,
            conversation_id=cid,
            sender_id=sender_id,
            body=body.body,
            content_hash=incoming_hash,
        )
        if created:
            await _push_new_message(sender_id, peer_id, cid, body.body)
            return _message_to_out(message)
        existing = message  # eşzamanlı idempotent tekrar yarışı kaybetti

    if existing.sender_id != sender_id:
        raise not_found("Mesaj bulunamadı")
    if existing.content_hash != incoming_hash:
        raise conflict("Bu mesaj id'si farklı bir içerikle zaten kayıtlı", {"message_id": body.id})
    response.status_code = status.HTTP_200_OK
    return _message_to_out(existing)


async def _push_new_message(sender_id: uuid.UUID, peer_id: uuid.UUID, cid: uuid.UUID, text: str) -> None:
    """Uygulama kapalıyken yeni mesaj bildirimi. `tag` = konuşma: aynı sohbetin
    bildirimleri üst üste yığılmaz, sonuncusu öncekinin yerini alır."""
    profile = (await social_client.fetch_profiles([sender_id])).get(str(sender_id))
    title = profile.display_name if profile else "Yeni mesaj"
    await push_client.notify(
        peer_id, title, text, channel="messages",
        data={
            "type": "CHAT_MESSAGE",
            "conversation_id": str(cid),
            # Alıcının gözünden karşı taraf = gönderen: bildirime basınca sohbet açılır.
            "peer_user_id": str(sender_id),
            "peer_name": title,
            "tag": f"chat-{cid}",
        },
    )


@router.post("/conversations/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    conversation_id: str,
    body: MarkReadIn,
    x_user_id: str | None = Header(default=None),
) -> None:
    """Okundu bilgisi konuşma dokümanında (`reads.{uid}.last_read_seq`) —
    karşı taraf onu dinleyiciyle görüyor (eski RECEIPT çerçevesinin yerine)."""
    me = require_user_id(x_user_id)
    cid = _parse_uuid(conversation_id)

    await _require_participant(cid, me)
    await conversations.mark_read(cid, me, body.up_to_seq)
