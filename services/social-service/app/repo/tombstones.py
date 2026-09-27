"""Silinen kullanıcı tombstone'u — `social_deleted_users/{user_id}` (Faz S10).

Hesap silme ile gecikmeli bir `workout.session` olayı yarışırsa tüketici bu
dokümana bakıp silinmiş kullanıcının snapshot'ını DİRİLTMİYOR.
"""

from __future__ import annotations

import uuid

from google.cloud import firestore

from app.db import db


def ref(user_id: uuid.UUID | str):
    return db.collection("deleted_users").document(str(user_id))


async def mark(user_id: uuid.UUID) -> None:
    await ref(user_id).set({"deleted_at": firestore.SERVER_TIMESTAMP})
