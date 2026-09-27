"""Mesajlar — `chat_conversations/{cid}/messages/{mid}`: idempotent yazım
(workout-service'in 201/200/409 merdiveni) ve `seq` ile sayfalı okuma (Faz S6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import firestore
from nabiz_firebase import run_contended_transaction

from app.repo import conversations


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


def _col(conversation_id: uuid.UUID):
    return conversations.ref(conversation_id).collection("messages")


def _to_message(conversation_id: uuid.UUID, message_id: str, d: dict) -> Message:
    return Message(
        id=uuid.UUID(message_id),
        conversation_id=conversation_id,
        seq=int(d["seq"]),
        sender_id=uuid.UUID(d["sender_id"]),
        body=d.get("body"),
        content_hash=d["content_hash"],
        redacted_at=d.get("redacted_at"),
        created_at=d["created_at"],
    )


async def find_by_id(conversation_id: uuid.UUID, message_id: uuid.UUID) -> Message | None:
    snap = await _col(conversation_id).document(str(message_id)).get()
    return _to_message(conversation_id, snap.id, snap.to_dict()) if snap.exists else None


async def insert(
    *,
    message_id: uuid.UUID,
    conversation_id: uuid.UUID,
    sender_id: uuid.UUID,
    body: str,
    content_hash: str,
) -> tuple[Message, bool]:
    """(mesaj, yeni_mi). Kimlik zaten varsa HİÇBİR ŞEY yazılmaz, mevcut döner.

    ★ SEQ ATAMASI ATOMİK ★ `next_seq` okunup artırılıyor ve mesaj AYNI
    transaction'da oluşturuluyor — iki eşzamanlı gönderim asla aynı `seq`'i
    almaz (Postgres'teki `UPDATE ... RETURNING next_seq - 1` satır kilidi).
    İki taraf aynı anda yazabildiği için yarışa dayanıklı yeniden deneme.
    """
    conv_ref = conversations.ref(conversation_id)
    msg_ref = _col(conversation_id).document(str(message_id))

    async def run(tx) -> tuple[dict, bool]:
        existing = await msg_ref.get(transaction=tx)
        if existing.exists:
            return existing.to_dict(), False
        conv = await conv_ref.get(transaction=tx)
        seq = int(conv.get("next_seq"))
        now = datetime.now(timezone.utc)
        data = {
            "seq": seq,
            "sender_id": str(sender_id),
            "body": body,
            "content_hash": content_hash,
            "created_at": now,
            "redacted_at": None,
        }
        tx.create(msg_ref, data)
        tx.update(conv_ref, {
            "next_seq": seq + 1,
            "last_message": {"id": str(message_id), "body": body, "sender_id": str(sender_id),
                             "created_at": now, "redacted": False},
            "last_message_at": now,
        })
        return data, True

    data, created = await run_contended_transaction(run)
    return _to_message(conversation_id, str(message_id), data), created


async def fetch_page(conversation_id: uuid.UUID, before_seq: int, limit: int) -> list[Message]:
    query = (
        _col(conversation_id)
        .where(filter=firestore.FieldFilter("seq", "<", before_seq))
        .order_by("seq", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    rows = [_to_message(conversation_id, s.id, s.to_dict()) async for s in query.stream()]
    # DESC sorgulandı (en yeniden geriye) ama görüntüleme ASC beklenir.
    return list(reversed(rows))


async def redact_by_sender(sender_id: uuid.UUID) -> int:
    """Hesap silme: gönderenin mesajlarında `body` NULL, `redacted_at` damgalı —
    satır SİLİNMEZ, karşı tarafın geçmişi kırılmaz (ADR 0014 Sonuçlar).

    Kullanıcının konuşmaları üzerinden gidiliyor: "tüm messages'ta
    sender_id == X" bir koleksiyon GRUBU sorgusu olurdu ve koleksiyon grubu
    kapsamlı indeks varsayılan olarak yok. Konuşma içinde `sender_id` eşitliği
    tek alanlı otomatik indeksle çalışıyor. İdempotent: zaten redakte olanlar
    yeniden damgalanmıyor.
    """
    count = 0
    for conv_snap in await conversations.for_user(sender_id):
        cid = uuid.UUID(conv_snap.id)
        query = _col(cid).where(filter=firestore.FieldFilter("sender_id", "==", str(sender_id)))
        async for snap in query.stream():
            if snap.get("redacted_at") is not None:
                continue
            await snap.reference.update({"body": None, "redacted_at": firestore.SERVER_TIMESTAMP})
            count += 1
        last = conv_snap.get("last_message") or {}
        if last.get("sender_id") == str(sender_id) and not last.get("redacted"):
            await conv_snap.reference.update({"last_message.body": None, "last_message.redacted": True})
    return count
