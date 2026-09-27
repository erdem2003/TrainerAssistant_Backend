"""`workout.session` tüketicisi — olay akışını okuma modeline yansıtır.

★ KAFKA → SÜREÇ İÇİ DAĞITICI (ADR 0019 karar 2) ★
Tüketici artık bir Kafka döngüsü değil, `nabiz_firebase.outbox` dağıtıcısına
kayıtlı bir işleyici (`register()`). Consumer group adı aynı kalıyor
(`settings.consumer_group`) — dağıtıcı teslim durumunu bu adla tutuyor.

★ PHASE 11'İN ÇIKIŞ KRİTERİ HÂLÂ GEÇERLİ ★
"Replay ile analytics sıfırdan yeniden hesaplanabiliyor". Bunu mümkün kılan
kararlar aynen duruyor:

  1. Replay = outbox koleksiyonunu baştan işlemek
     (`dispatcher_for("workout_outbox").replay(group=settings.consumer_group)`).
  2. Yazma UPSERT — replay aynı fact'i güncel mantıkla YENİDEN ÜRETİYOR; özet
     eski katkıyı çıkarıp yenisini eklediği için toplam ikiye katlanmıyor.
  3. `processed_events` kaydı replay'de BİLİNÇLİ olarak atlanabiliyor
     (`REPLAY_MODE`).

★ İŞLEME + IDEMPOTENCY KAYDI AYNI TRANSACTION'DA ★ Postgres'teki kuralın
aynısı: kayıt yazılıp fact yazımı patlarsa olay "işlendi" sayılır ve veri
sonsuza kadar eksik kalırdı.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from google.cloud import firestore
from nabiz_firebase import outbox as shared_outbox

from app.config import settings
from app.db import db
from app.repo import facts

logger = logging.getLogger(__name__)

EVENT_WORKOUT_COMPLETED = "WorkoutCompleted"


def _from_epoch_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


async def handle(envelope: dict) -> bool:
    """Tek bir olayı işler. `True` = yazıldı, `False` = atlandı.

    İstisna fırlatırsa dağıtıcı olayı kuyrukta tutar ve yeniden dener
    (Kafka'da offset'i ilerletmemenin karşılığı).
    """
    event_type = envelope.get("event_type")
    if event_type != EVENT_WORKOUT_COMPLETED:
        # Bilinmeyen tür HATA DEĞİL: aynı topic'e ileride başka olaylar da
        # gelebilir ve bu tüketici yalnızca ilgilendiğini işler.
        return False

    try:
        event_id = uuid.UUID(envelope["event_id"])
        payload = envelope["payload"]
        workout_id = uuid.UUID(payload["workout_id"])
        fact = facts.build_fact(
            user_id=uuid.UUID(payload["user_id"]),
            exercise_id=payload["exercise_id"],
            started_at=_from_epoch_ms(payload["started_at"]),
            ended_at=_from_epoch_ms(payload.get("ended_at")),
            total_sets=payload.get("total_sets", 0),
            total_reps=payload.get("total_reps", 0),
            # Eski olaylar bu alanları TAŞIMIYOR olabilir (Phase 11 öncesi).
            # Varsayılanla geçmek, replay'in eski kayıtlarda patlamasını engelliyor.
            reps_with_errors=payload.get("reps_with_errors", 0),
            best_set_reps=payload.get("best_set_reps", 0),
            total_active_seconds=payload.get("total_active_seconds", 0.0),
            form_errors=payload.get("form_errors", {}),
        )
    except (KeyError, ValueError, TypeError):
        # Bozuk mesaj KUYRUĞU TIKAMAMALI. Loglanıp geçiliyor; yeniden denemek
        # düzeltmeyecek, çünkü sorun mesajın kendisinde.
        logger.error("bozuk olay zarfı, atlanıyor event_id=%s", envelope.get("event_id"))
        return False

    processed_ref = db.collection("processed_events").document(str(event_id))
    replay = settings.replay_mode

    @firestore.async_transactional
    async def run(tx) -> bool:
        # ★ IDEMPOTENCY ★ Normal çalışmada tekrar atlanır; replay'de YENİDEN
        # işlenir — bu yüzden bayrak. Okuma transaction içinde: iki eşzamanlı
        # teslim aynı olayı iki kez işleyemez.
        if not replay and (await processed_ref.get(transaction=tx)).exists:
            return False
        await facts.upsert_in_tx(tx, workout_id, fact)
        if not replay:
            tx.create(processed_ref, {"event_type": EVENT_WORKOUT_COMPLETED,
                                      "processed_at": firestore.SERVER_TIMESTAMP})
        return True

    written = await run(db.client.transaction())
    if written:
        logger.info("olay yansıtıldı event_id=%s workout_id=%s", event_id, workout_id)
    else:
        logger.debug("olay zaten işlenmiş, atlanıyor event_id=%s", event_id)
    return written


def register() -> None:
    """Tüketiciyi `workout.session` topic'ine bağlar (tek süreçli giriş noktası
    ya da bu servisin `lifespan`'i çağırır)."""
    shared_outbox.subscribe(settings.topic_workout_session, settings.consumer_group, handle)


def unregister() -> None:
    shared_outbox.unsubscribe(settings.topic_workout_session, settings.consumer_group)
