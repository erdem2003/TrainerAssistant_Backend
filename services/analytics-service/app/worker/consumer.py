"""`workout.session` tuketicisi — olay akisini okuma modeline yansitir.

★ PHASE 11'IN CIKIS KRITERI BURADA ★
Roadmap: "event replay ile analytics sifirdan yeniden hesaplanabiliyor".
Bunu mumkun kilan uc karar:

  1. Consumer group offset'i Kafka'da tutuluyor (`auto_offset_reset="earliest"`),
     yani offset sifirlaninca akis basindan yeniden okunuyor.
  2. Yazma UPSERT — replay ayni satiri guncel mantikla YENIDEN URETIYOR
     (`DO NOTHING` olsaydi replay hicbir sey degistirmezdi).
  3. `processed_events` kaydi, replay'de BILINCLI olarak atlanabiliyor
     (`REPLAY_MODE`), cunku normal calismada tekrari yutmak isteniyor ama
     replay'de tam tersi isteniyor.

★ NEDEN AYRI SUREC, FastAPI ICINDE DEGIL ★
Tuketici surekli calisan bir dongu; HTTP sunucusunun yasam dongusune baglamak,
sunucu yeniden baslatildiginda tuketimi kesintiye ugratirdi. `auth-email-worker`
ve `workout-outbox-relay` ile ayni desen.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.correlation import configure_logging
from app.db import db
from app.repo import facts, processed_events

logger = logging.getLogger(__name__)

EVENT_WORKOUT_COMPLETED = "WorkoutCompleted"


def _from_epoch_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


async def handle(conn, envelope: dict) -> bool:
    """Tek bir olayi isler. `True` = yazildi, `False` = atlandi."""
    event_type = envelope.get("event_type")
    if event_type != EVENT_WORKOUT_COMPLETED:
        # Bilinmeyen tur HATA DEGIL: ayni topic'e ileride baska olaylar da
        # gelebilir ve bu tuketici yalnizca ilgilendigini isler.
        return False

    try:
        event_id = uuid.UUID(envelope["event_id"])
        payload = envelope["payload"]
    except (KeyError, ValueError, TypeError):
        # Bozuk mesaj KUYRUGU TIKAMAMALI. Loglanip geciliyor; yeniden denemek
        # duzeltmeyecek, cunku sorun mesajin kendisinde.
        logger.error("bozuk olay zarfı, atlanıyor: %s", envelope)
        return False

    # ★ IDEMPOTENCY ★
    # Kafka at-least-once veriyor. Normal çalışmada aynı olay ikinci kez
    # gelirse atlanmalı; replay'de ise YENİDEN işlenmeli — bu yüzden bayrak.
    if not settings.replay_mode:
        first_time = await processed_events.claim(
            conn, event_id, EVENT_WORKOUT_COMPLETED
        )
        if not first_time:
            logger.debug("olay zaten işlenmiş, atlanıyor event_id=%s", event_id)
            return False

    await facts.upsert(
        conn,
        workout_id=uuid.UUID(payload["workout_id"]),
        user_id=uuid.UUID(payload["user_id"]),
        exercise_id=payload["exercise_id"],
        started_at=_from_epoch_ms(payload["started_at"]),
        ended_at=_from_epoch_ms(payload.get("ended_at")),
        total_sets=payload.get("total_sets", 0),
        total_reps=payload.get("total_reps", 0),
        # Eski olaylar bu alanları TAŞIMIYOR olabilir (Phase 11 öncesi
        # outbox satırları). Varsayılanla geçmek, replay'in eski kayıtlarda
        # patlamasını engelliyor.
        reps_with_errors=payload.get("reps_with_errors", 0),
        best_set_reps=payload.get("best_set_reps", 0),
        total_active_seconds=payload.get("total_active_seconds", 0.0),
        form_errors=payload.get("form_errors", {}),
    )
    return True


async def run() -> None:
    configure_logging(settings.log_level)
    await db.connect()
    await db.migrate()

    consumer = AIOKafkaConsumer(
        settings.topic_workout_session,
        bootstrap_servers=settings.kafka_bootstrap,
        group_id=settings.consumer_group,
        # ★ BASTAN OKU ★
        # Yeni bir consumer group (ya da offset sıfırlanmış bir group) akışı
        # EN BAŞTAN okur. Replay'i mümkün kılan ayar bu; `latest` olsaydı
        # geçmiş olaylar bir daha hiç görünmezdi.
        auto_offset_reset="earliest",
        # ★ OFFSET ELLE İŞARETLENİYOR ★
        # Otomatik commit, mesajı işlemeden ÖNCE offset'i ilerletebilir ve
        # süreç o anda ölürse olay kaybolur. Yazma başarılı olduktan sonra
        # commit etmek, at-least-once garantisinin gereği.
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info(
        "tüketici başladı topic=%s group=%s replay=%s",
        settings.topic_workout_session, settings.consumer_group, settings.replay_mode,
    )

    try:
        async for message in consumer:
            try:
                envelope = json.loads(message.value)
            except json.JSONDecodeError:
                logger.error("JSON ayrıştırılamadı, atlanıyor offset=%s", message.offset)
                await consumer.commit()
                continue

            try:
                async with db.pool.acquire() as conn:
                    # İşleme ve idempotency kaydı AYNI transaction'da: kayıt
                    # yazılıp yazma patlarsa olay "işlendi" sayılır ve veri
                    # sonsuza kadar eksik kalırdı.
                    async with conn.transaction():
                        written = await handle(conn, envelope)
            except Exception:
                # Yazma patladıysa offset İLERLETİLMİYOR: aynı mesaj tekrar
                # denenecek. Kuyruk tıkanabilir ama veri kaybolmaz — bu
                # ölçekte doğru tercih.
                logger.exception("olay işlenemedi offset=%s", message.offset)
                await asyncio.sleep(settings.retry_seconds)
                continue

            await consumer.commit()
            if written:
                logger.info(
                    "olay yansıtıldı offset=%s event_id=%s",
                    message.offset, envelope.get("event_id"),
                )
    finally:
        await consumer.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
