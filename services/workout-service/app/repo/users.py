"""Kullanıcının tüm antrenman verisi — hesap silme için."""

from __future__ import annotations

import uuid

from google.cloud import firestore

from app.db import db, user_doc


async def delete_all(user_id: uuid.UUID) -> int:
    """Antrenmanları, programı ve küresel kimlik kayıtlarını siler.

    Kimlik kayıtları (`workout_workout_ids`) kullanıcının altında değil, bu
    yüzden ayrıca sorgulanıyor: kalsalardı silinmiş kullanıcının `user_id`'si
    sonsuza kadar dururdu.

    Outbox dokümanları SİLİNMİYOR — Postgres dalındaki davranışla aynı (outbox
    satırları silmede tutuluyordu; Kafka topic'i de olayları saklıyordu).
    Tüketiciler kendi silme uçlarıyla temizleniyor.
    """
    deleted = await db.client.recursive_delete(user_doc(user_id))
    ids = db.collection("workout_ids").where(filter=firestore.FieldFilter("user_id", "==", str(user_id)))
    async for snap in ids.stream():
        await snap.reference.delete()
        deleted += 1
    return deleted
