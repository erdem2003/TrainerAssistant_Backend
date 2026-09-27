"""Bildirimler (ADR 0014, Faz S8) — `social_users/{recipient}/notifications/{key}`.

★ DOĞAL ANAHTAR = DOKÜMAN KİMLİĞİ ★ Postgres'teki
`UNIQUE (recipient_id, type, actor_id, subject_id)` + `ON CONFLICT DO UPDATE`
deseninin karşılığı: `{type}_{actor}_{subject}` kimliğine `set()` — aynı eylem
tekrarlandığında (beğen → kaldır → beğen) TEK doküman kalır, `created_at`
yenilenir, `read_at` SIFIRLANIR (yeni bir olay, tekrar "okunmamış").
Bildirimin dışa görünen `id`'si de doğal anahtardan deterministik (UUIDv5):
Postgres'te UPSERT ilk satırın `id`'sini koruyordu, sonuç aynı.

★ GERÇEK ZAMANLI İLETİM ★ Redis pub/sub + chat-service WebSocket'i kalktı
(ADR 0019 karar 5): mobil bu alt koleksiyonu Firestore snapshot dinleyicisiyle
izliyor; doküman yazımı sinyalin KENDİSİ.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import firestore

from app.db import db, user_doc

_ID_NAMESPACE = uuid.UUID("0b8f1f3e-5a51-4c55-9d4e-1f6f2a9c7e21")


@dataclass(frozen=True)
class UpsertResult:
    id: uuid.UUID
    created_at: datetime


def _col(recipient_id: uuid.UUID):
    return user_doc(recipient_id).collection("notifications")


def natural_key(notification_type: str, actor_id: uuid.UUID, subject_id: uuid.UUID) -> str:
    return f"{notification_type}_{actor_id}_{subject_id}"


async def upsert(
    *,
    recipient_id: uuid.UUID,
    notification_type: str,
    actor_id: uuid.UUID,
    subject_id: uuid.UUID,
    tx: firestore.AsyncTransaction | None = None,
) -> UpsertResult:
    """`tx` verilirse çağıranın transaction'ına eklenir (arkadaşlık/beğeni ile
    atomik); verilmezse tek başına yazılır."""
    key = natural_key(notification_type, actor_id, subject_id)
    notification_id = uuid.uuid5(_ID_NAMESPACE, f"{recipient_id}:{key}")
    now = datetime.now(timezone.utc)
    data = {
        "id": str(notification_id),
        "type": notification_type,
        "actor_id": str(actor_id),
        "subject_id": str(subject_id),
        "created_at": now,
        "read_at": None,
    }
    ref = _col(recipient_id).document(key)
    if tx is not None:
        tx.set(ref, data)
    else:
        await ref.set(data)
    return UpsertResult(id=notification_id, created_at=now)


async def fetch_page(recipient_id: uuid.UUID, before: datetime, limit: int) -> list[dict]:
    query = (
        _col(recipient_id)
        .where(filter=firestore.FieldFilter("created_at", "<", before))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [snap.to_dict() async for snap in query.stream()]


async def count_unread(recipient_id: uuid.UUID) -> int:
    """`count()` toplaması — 1000 indeks girdisine kadar 1 okuma."""
    query = _col(recipient_id).where(filter=firestore.FieldFilter("read_at", "==", None))
    result = await query.count().get()
    return int(result[0][0].value)


async def mark_all_read(recipient_id: uuid.UUID) -> None:
    query = _col(recipient_id).where(filter=firestore.FieldFilter("read_at", "==", None))
    now = datetime.now(timezone.utc)
    batch = db.client.batch()
    pending = 0
    async for snap in query.stream():
        batch.update(snap.reference, {"read_at": now})
        pending += 1
        if pending == 400:  # yığın sınırı 500 yazım
            await batch.commit()
            batch, pending = db.client.batch(), 0
    if pending:
        await batch.commit()
