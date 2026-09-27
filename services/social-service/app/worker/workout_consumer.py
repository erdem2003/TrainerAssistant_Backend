"""`workout.session` tuketicisi — sosyal servisin kendi izdusumu (ADR 0014,
Faz S3). `analytics-service/app/worker/consumer.py` ile AYNI DESEN, ama iki
bilincli farkla:

  1. ★ SILINEN KULLANICI TOMBSTONE KONTROLU ★ Hesap silindiginde
     `deleted_users`'a bir satir yaziliyor (app/routers/internal.py). Silme
     ile ayni ANDA Kafka'da o kullanicinin gecikmis bir `WorkoutCompleted`
     eventi kuyrukta olabilir — bu tuketici o eventi gormeden ONCE ya da
     SONRA calisabilir. Once calisirsa event normal islenir, sonra silme
     gelir ve zaten `internal.py` `workout_snapshots`'tan siler. Sonra
     calisirsa (silme once) tombstone kontrolu event'i YOK SAYAR — yoksa
     silinmis bir kullanicinin satiri Kafka replay'inde ya da gecikmeli
     teslimde DIRILIR.

  2. ★ HATA DONGUSUNDE OFFSET GERI SARILIYOR ★ `analytics-service`'in
     orijinal deseninde bir mesaj islenirken exception firlarsa, `commit()`
     cagrilmiyor (dogru) ama `AIOKafkaConsumer`'in ic okuma konumu o mesaji
     zaten GECMIS oluyor — bir sonraki `async for` adimi BIR SONRAKI mesaji
     getirir, basarisiz olani degil. Surec bu sekilde calismaya devam
     ettigi surece o mesaj bir daha hic denenmez (yalnizca surec YENIDEN
     BASLARSA son commit'lenen offset'ten okur ve o zaman denenir) — sessiz
     veri kaybina yol aciyordu. Burada `consumer.seek()` ile basarisiz
     mesajin offset'ine GERI DONULUYOR, boylece ayni surec icinde tekrar
     denenir.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer, TopicPartition

from app.config import settings
from app.correlation import configure_logging
from app.db import db
from app.repo import posts, processed_events, snapshots

logger = logging.getLogger(__name__)

EVENT_WORKOUT_COMPLETED = "WorkoutCompleted"

_IS_USER_DELETED = "SELECT 1 FROM deleted_users WHERE user_id = $1"


def _from_epoch_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


async def handle(conn, envelope: dict) -> bool:
    """Tek bir olayi isler. `True` = yazildi, `False` = atlandi."""
    event_type = envelope.get("event_type")
    if event_type != EVENT_WORKOUT_COMPLETED:
        return False

    try:
        event_id = uuid.UUID(envelope["event_id"])
        payload = envelope["payload"]
        user_id = uuid.UUID(payload["user_id"])
    except (KeyError, ValueError, TypeError):
        logger.error("bozuk olay zarfı, atlanıyor: %s", envelope)
        return False

    if await conn.fetchval(_IS_USER_DELETED, user_id):
        logger.info("silinmiş kullanıcının eventi yok sayıldı user_id=%s", user_id)
        return False

    if not settings.replay_mode:
        first_time = await processed_events.claim(
            conn, event_id, EVENT_WORKOUT_COMPLETED
        )
        if not first_time:
            logger.debug("olay zaten işlenmiş, atlanıyor event_id=%s", event_id)
            return False

    workout_id = uuid.UUID(payload["workout_id"])
    await snapshots.upsert(
        conn,
        workout_id=workout_id,
        user_id=user_id,
        exercise_id=payload["exercise_id"],
        started_at=_from_epoch_ms(payload["started_at"]),
        ended_at=_from_epoch_ms(payload.get("ended_at")),
        total_sets=payload.get("total_sets", 0),
        total_reps=payload.get("total_reps", 0),
        reps_with_errors=payload.get("reps_with_errors", 0),
        best_set_reps=payload.get("best_set_reps", 0),
        total_active_seconds=payload.get("total_active_seconds", 0.0),
        form_errors=payload.get("form_errors", {}),
    )
    # ★ TERFİ (Faz S4) ★ Bu snapshot bekleyen bir gönderiyi VISIBLE'a
    # taşıyabilir — `author_id = user_id` eşleşmesi zorunlu, yoksa başkasının
    # workout_id'siyle açılmış bir gönderi asla görünür olmaz (app/repo/
    # posts.py, "posts_author_workout_idx" gerekçesiyle aynı).
    if await posts.promote_pending(conn, workout_id, user_id):
        logger.info("gönderi VISIBLE oldu workout_id=%s", workout_id)
    return True


async def _sweep_stale_posts_loop() -> None:
    """15 dakikadır PENDING_SNAPSHOT kalan gönderileri siler (Faz S4).

    Ayrı bir asyncio görevi olarak tüketici döngüsüyle birlikte koşuyor —
    ayrı bir konteyner/süreç açmaya değmeyecek kadar ucuz bir iş, ve zaten
    `social-consumer`'ın veritabanı havuzunu paylaşabiliyor.
    """
    while True:
        await asyncio.sleep(60)
        try:
            async with db.pool.acquire() as conn:
                deleted = await posts.sweep_stale_pending(conn)
            if deleted:
                logger.info("bayat PENDING_SNAPSHOT gönderi silindi adet=%d", deleted)
        except Exception:
            logger.exception("süpürme başarısız, bir sonraki turda tekrar denenecek")


async def run() -> None:
    configure_logging(settings.log_level)
    await db.connect()
    await db.migrate()

    sweep_task = asyncio.create_task(_sweep_stale_posts_loop())

    consumer = AIOKafkaConsumer(
        settings.topic_workout_session,
        bootstrap_servers=settings.kafka_bootstrap,
        group_id=settings.consumer_group,
        auto_offset_reset="earliest",
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
                    async with conn.transaction():
                        written = await handle(conn, envelope)
            except Exception:
                # ★ GERI SARMA ★ Islem patladiysa bu mesaji GERCEKTEN yeniden
                # denemek icin ic okuma konumunu mesajin KENDI offset'ine
                # geri aliyoruz — aksi halde `async for` bir sonraki dongude
                # bir SONRAKI mesaji getirir ve bu, surec canli kaldigi
                # surece bir daha hic denenmez.
                tp = TopicPartition(message.topic, message.partition)
                consumer.seek(tp, message.offset)
                logger.exception(
                    "olay işlenemedi, offset'e geri sarılıyor offset=%s", message.offset
                )
                await asyncio.sleep(settings.retry_seconds)
                continue

            await consumer.commit()
            if written:
                logger.info(
                    "olay yansıtıldı offset=%s event_id=%s",
                    message.offset, envelope.get("event_id"),
                )
    finally:
        sweep_task.cancel()
        await consumer.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
