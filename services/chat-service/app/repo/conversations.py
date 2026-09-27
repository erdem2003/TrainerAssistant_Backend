"""Konuşmalar — `chat_conversations/{id}` (ADR 0014 Faz S6, yerleşim `app/db.py`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from app.db import db

_ID_NAMESPACE = uuid.UUID("5d1e7c38-2b9a-4f0e-8c61-3a7d9e2f4b10")


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """`friendships._pair` ile aynı kanonik sıralama — bkz. social-service."""
    return (a, b) if str(a) < str(b) else (b, a)


def conversation_id_for(a: uuid.UUID, b: uuid.UUID) -> uuid.UUID:
    low, high = _pair(a, b)
    return uuid.uuid5(_ID_NAMESPACE, f"{low}:{high}")


def ref(conversation_id: uuid.UUID):
    return db.collection("conversations").document(str(conversation_id))


def read_field(user_id: uuid.UUID, name: str) -> str:
    """`reads.{uuid}.{alan}` — UUID'deki tire nedeniyle alan yolu tırnaklı."""
    return FieldPath("reads", str(user_id), name).to_api_repr()


@dataclass(frozen=True)
class ConversationSummary:
    conversation_id: uuid.UUID
    peer_id: uuid.UUID
    unread_count: int
    last_body: str | None
    last_sender_id: uuid.UUID | None
    last_created_at: datetime | None
    last_redacted: bool


async def get_or_create(user_a: uuid.UUID, user_b: uuid.UUID) -> uuid.UUID:
    """Deterministik kimlik + `create()`: eşzamanlı iki istek aynı dokümanı
    oluşturmaya çalışır, biri AlreadyExists alır — kayıp yok, çift kayıt yok
    (Postgres'teki `ON CONFLICT DO NOTHING RETURNING` yarış dalının karşılığı)."""
    low, high = _pair(user_a, user_b)
    conversation_id = conversation_id_for(user_a, user_b)
    try:
        await ref(conversation_id).create({
            "user_low": str(low),
            "user_high": str(high),
            "participants": [str(low), str(high)],
            "next_seq": 1,
            "created_at": datetime.now(timezone.utc),
            "last_message": None,
            "last_message_at": None,
            "reads": {
                str(low): {"last_read_seq": 0, "last_read_at": None, "left_at": None},
                str(high): {"last_read_seq": 0, "last_read_at": None, "left_at": None},
            },
        })
    except AlreadyExists:
        pass
    return conversation_id


async def find(conversation_id: uuid.UUID) -> dict | None:
    snap = await ref(conversation_id).get()
    return snap.to_dict() if snap.exists else None


def peer_of(conversation: dict, user_id: uuid.UUID) -> uuid.UUID | None:
    others = [p for p in conversation.get("participants", []) if p != str(user_id)]
    return uuid.UUID(others[0]) if others else None


def is_participant(conversation: dict | None, user_id: uuid.UUID) -> bool:
    return conversation is not None and str(user_id) in conversation.get("participants", [])


async def mark_read(conversation_id: uuid.UUID, user_id: uuid.UUID, up_to_seq: int) -> None:
    """★ MAKSİMUM SEMANTİĞİ ★ Postgres'teki `GREATEST(last_read_seq, $3)`:
    Firestore'un sunucu tarafı `Maximum` dönüşümü — geç gelen eski bir okundu
    bildirimi ilerlemeyi GERİ ALAMAZ, transaction gerekmez."""
    await ref(conversation_id).update({
        read_field(user_id, "last_read_seq"): firestore.Maximum(up_to_seq),
        read_field(user_id, "last_read_at"): firestore.SERVER_TIMESTAMP,
    })


async def list_for_user(user_id: uuid.UUID) -> list[ConversationSummary]:
    """Konuşma başına tek doküman; son mesaj ve okunmamış sayısı dokümanın
    üzerinde. Sıralama: son mesaj (yoksa oluşturulma) yeniden eskiye."""
    query = db.collection("conversations").where(
        filter=firestore.FieldFilter("participants", "array_contains", str(user_id))
    )
    rows = []
    async for snap in query.stream():
        d = snap.to_dict()
        peer = peer_of(d, user_id)
        if peer is None:
            continue
        last = d.get("last_message") or {}
        my_read = int(((d.get("reads") or {}).get(str(user_id)) or {}).get("last_read_seq", 0))
        rows.append((
            d.get("last_message_at") or d["created_at"],
            ConversationSummary(
                conversation_id=uuid.UUID(snap.id),
                peer_id=peer,
                unread_count=max(0, int(d.get("next_seq", 1)) - 1 - my_read),
                last_body=last.get("body"),
                last_sender_id=uuid.UUID(last["sender_id"]) if last.get("sender_id") else None,
                last_created_at=last.get("created_at"),
                last_redacted=bool(last.get("redacted")),
            ),
        ))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [summary for _, summary in rows]


async def for_user(user_id: uuid.UUID) -> list:
    """Kullanıcının tüm konuşma snapshot'ları (hesap silme)."""
    query = db.collection("conversations").where(
        filter=firestore.FieldFilter("participants", "array_contains", str(user_id))
    )
    return [snap async for snap in query.stream()]


async def mark_left(conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Faz S10: hesap silindiğinde konuşma SİLİNMEZ — geçmiş karşı tarafın
    listesinde kalır (ADR 0014 Sonuçlar). Yalnızca `left_at` damgalanır."""
    await ref(conversation_id).update({read_field(user_id, "left_at"): firestore.SERVER_TIMESTAMP})
