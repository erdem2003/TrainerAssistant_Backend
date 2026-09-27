"""İşlenmiş event kaydı — aynı event iki kez işlenmesin (idempotent consumer)."""

from __future__ import annotations

import uuid

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from app.db import db


async def claim(event_id: uuid.UUID, event_type: str) -> bool:
    """Event'i ilk kez görüyorsak `True`, tekrarsa `False`.

    `create()` doküman varsa `AlreadyExists` fırlatır — Postgres'teki
    `ON CONFLICT DO NOTHING`'in atomik karşılığı.
    """
    try:
        await db.collection("processed_events").document(str(event_id)).create(
            {"event_type": event_type, "processed_at": firestore.SERVER_TIMESTAMP}
        )
        return True
    except AlreadyExists:
        return False


async def exists(event_id: uuid.UUID) -> bool:
    return (await db.collection("processed_events").document(str(event_id)).get()).exists
