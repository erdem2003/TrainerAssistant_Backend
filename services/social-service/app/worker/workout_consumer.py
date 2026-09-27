"""`workout.session` tüketicisi — sosyal servisin kendi izdüşümü (ADR 0014 Faz S3).

★ KAFKA → SÜREÇ İÇİ DAĞITICI (ADR 0019 karar 2) ★
Artık ayrı bir Kafka süreci değil, `nabiz_firebase.outbox` dağıtıcısına kayıtlı
bir işleyici (`register()`); grup adı aynı (`social-workout-v1`) ve analytics'ten
KASITLI farklı — her grup kendi teslim durumunu tutuyor.

Kafka dalındaki iki bilinçli fark korunuyor:
  1. ★ SİLİNEN KULLANICI TOMBSTONE KONTROLÜ ★ Hesap silindikten sonra gelen
     gecikmeli (ya da replay'deki) olay snapshot'ı DİRİLTMEZ.
  2. ★ BAŞARISIZ OLAY KAYBOLMAZ ★ Kafka'da `consumer.seek()` ile geri
     sarılıyordu; burada işleyici istisna fırlatınca dağıtıcı olayı kuyrukta
     tutup yeniden deniyor — aynı garanti, taşıyıcının doğal davranışı.

★ TEK TRANSACTION ★ tombstone + idempotency kaydı + snapshot + sahiplik dizini +
bekleyen gönderinin terfisi. Postgres'te de tek transaction'dı; kayıt yazılıp
snapshot patlarsa olay "işlendi" sayılır ve veri sonsuza kadar eksik kalırdı.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from google.cloud import firestore
from nabiz_firebase import outbox as shared_outbox

from app.config import settings
from app.db import db
from app.repo import posts, snapshots, tombstones

logger = logging.getLogger(__name__)

EVENT_WORKOUT_COMPLETED = "WorkoutCompleted"


def _from_epoch_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


async def handle(envelope: dict) -> bool:
    """Tek bir olayı işler. `True` = yazıldı, `False` = atlandı."""
    if envelope.get("event_type") != EVENT_WORKOUT_COMPLETED:
        return False

    try:
        event_id = uuid.UUID(envelope["event_id"])
        payload = envelope["payload"]
        user_id = uuid.UUID(payload["user_id"])
        workout_id = uuid.UUID(payload["workout_id"])
        data = {
            "exercise_id": payload["exercise_id"],
            "started_at": _from_epoch_ms(payload["started_at"]),
            "ended_at": _from_epoch_ms(payload.get("ended_at")),
            "total_sets": int(payload.get("total_sets", 0)),
            "total_reps": int(payload.get("total_reps", 0)),
            "reps_with_errors": int(payload.get("reps_with_errors", 0)),
            "best_set_reps": int(payload.get("best_set_reps", 0)),
            "total_active_seconds": float(payload.get("total_active_seconds", 0.0)),
            "form_errors": {str(k): int(v) for k, v in (payload.get("form_errors") or {}).items()},
        }
    except (KeyError, ValueError, TypeError):
        logger.error("bozuk olay zarfı, atlanıyor event_id=%s", envelope.get("event_id"))
        return False

    processed_ref = db.collection("processed_events").document(str(event_id))
    replay = settings.replay_mode

    @firestore.async_transactional
    async def run(tx) -> str:
        # Okumalar yazmalardan ÖNCE (Firestore transaction kuralı).
        if (await tombstones.ref(user_id).get(transaction=tx)).exists:
            return "deleted"
        if not replay and (await processed_ref.get(transaction=tx)).exists:
            return "duplicate"
        pending = await posts.read_pending_in_tx(tx, workout_id, user_id)

        snapshots.upsert_in_tx(tx, workout_id=workout_id, user_id=user_id, data=data)
        if pending is not None:
            posts.promote_in_tx(tx, pending)
        if not replay:
            tx.create(processed_ref, {"event_type": EVENT_WORKOUT_COMPLETED,
                                      "processed_at": firestore.SERVER_TIMESTAMP})
        return "promoted" if pending is not None else "written"

    outcome = await run(db.client.transaction())
    if outcome == "deleted":
        logger.info("silinmiş kullanıcının eventi yok sayıldı user_id=%s", user_id)
    elif outcome == "duplicate":
        logger.debug("olay zaten işlenmiş, atlanıyor event_id=%s", event_id)
    elif outcome == "promoted":
        logger.info("gönderi VISIBLE oldu workout_id=%s", workout_id)
    return outcome in ("written", "promoted")


def register() -> None:
    shared_outbox.subscribe(settings.topic_workout_session, settings.consumer_group, handle)


def unregister() -> None:
    shared_outbox.unsubscribe(settings.topic_workout_session, settings.consumer_group)


async def sweep_stale_posts_loop() -> None:
    """15 dakikadır PENDING_SNAPSHOT kalan gönderileri siler (Faz S4).

    Artık servisin `lifespan`'inde koşan bir asyncio görevi (Kafka tüketici
    süreci kalktı). Aralık okuma kotasına göre: boş sorgu da 1 okuma sayılıyor.
    """
    while True:
        await asyncio.sleep(settings.pending_sweep_seconds)
        try:
            deleted = await posts.sweep_stale_pending()
            if deleted:
                logger.info("bayat PENDING_SNAPSHOT gönderi silindi adet=%d", deleted)
        except Exception:
            logger.exception("süpürme başarısız, bir sonraki turda tekrar denenecek")
