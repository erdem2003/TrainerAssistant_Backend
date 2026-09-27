"""workout-service'in outbox'ı — `workout_outbox/{event_id}` (ADR 0019 karar 2).

Kuyruk mantığı (teslim, yeniden deneme, replay) paylaşılan katmanda:
`nabiz_firebase.outbox`. Burada yalnızca bu servisin koleksiyonu ve dağıtıcısı
bağlanıyor. Postgres'teki `claim_batch/mark_published/mark_failed` ve Kafka
relay'i (`app/kafka.py`, `app/worker/outbox_relay.py`) bunun yerine geçti.
"""

from __future__ import annotations

import uuid

from google.cloud import firestore
from nabiz_firebase import outbox as shared_outbox

from app.config import settings
from app.db import db

COLLECTION = "outbox"


def collection() -> firestore.AsyncCollectionReference:
    return db.collection(COLLECTION)


def dispatcher() -> shared_outbox.OutboxDispatcher:
    return shared_outbox.dispatcher_for(
        f"{db.root}_{COLLECTION}",
        poll_seconds=settings.outbox_poll_seconds,
        batch_size=settings.outbox_batch_size,
        max_attempts=settings.outbox_max_attempts,
    )


def enqueue(
    tx: firestore.AsyncTransaction,
    *,
    event_type: str,
    topic: str,
    partition_key: str,
    payload: dict,
    correlation_id: str | None,
) -> uuid.UUID:
    """ÇAĞIRANIN transaction'ına yazar — outbox'ın tüm anlamı bu."""
    return shared_outbox.enqueue(
        tx,
        collection(),
        event_type=event_type,
        topic=topic,
        partition_key=partition_key,
        payload=payload,
        correlation_id=correlation_id,
    )
