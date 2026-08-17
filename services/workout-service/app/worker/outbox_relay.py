"""outbox tablosunu tarayip olaylari Kafka'ya yayinlayan arka plan sureci.

`auth-service/app/worker/outbox_worker.py` ile ayni iskelet; farki, yayin hedefi:
orada HTTP fanout + e-posta, burada Kafka. Repo fonksiyonlari (`claim_batch`,
`mark_published`, `mark_failed`) ZATEN yazilmisti — Phase 11'in eksigi yalnizca
bu dongu ve tuketici tarafiydi.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.correlation import configure_logging
from app.db import db
from app.kafka import EventPublisher
from app.repo import outbox

logger = logging.getLogger(__name__)


async def process_once(publisher: EventPublisher) -> int:
    """Bir tur: hazır satırları al, yayınla, işaretle."""
    published = 0

    async with db.pool.acquire() as conn:
        # ★ TRANSACTION SATIRLARI KILITLIYOR ★
        # `claim_batch` `FOR UPDATE SKIP LOCKED` kullaniyor: birden fazla relay
        # ornegi ayni anda kossa bile ayni satiri iki kez almiyorlar. Bu yuzden
        # relay yatay olarak olceklenebilir — ama tek ornek de yeterli.
        async with conn.transaction():
            rows = await outbox.claim_batch(
                conn, settings.outbox_batch_size, settings.outbox_max_attempts
            )

            for row in rows:
                try:
                    await publisher.publish(
                        topic=row.topic,
                        event_id=row.id,
                        event_type=row.event_type,
                        partition_key=row.partition_key,
                        payload=row.payload,
                        occurred_at=row.created_at,
                    )
                except Exception as exc:
                    # Satır SİLİNMİYOR, sayaç artıyor. Kafka geçici olarak
                    # ayakta değilse bir sonraki turda tekrar denenecek;
                    # `attempts` tavana ulaşınca satır artık alınmıyor ve
                    # `last_error` neden başarısız olduğunu saklıyor.
                    logger.warning("yayınlanamadı id=%s: %s", row.id, exc)
                    await outbox.mark_failed(conn, row.id, str(exc))
                    continue

                await outbox.mark_published(conn, row.id)
                published += 1

    return published


async def run() -> None:
    configure_logging(settings.log_level)
    await db.connect()

    publisher = EventPublisher()
    await publisher.start()

    logger.info("outbox relay başladı (topic'ler satır bazında)")
    try:
        while True:
            try:
                sent = await process_once(publisher)
            except Exception:
                # Tek bir tur patlarsa süreç ÖLMEZ: veritabanı bağlantısı
                # geçici olarak kopmuş olabilir. Bir sonraki turda yeniden
                # denenir; ölmek, kimsenin fark etmediği bir duruş üretirdi.
                logger.exception("relay turu başarısız")
                sent = 0

            if sent:
                logger.info("%d olay yayınlandı", sent)

            # Boşta bekleme: outbox boşsa veritabanını sürekli sorgulamanın
            # anlamı yok. Gecikme bu aralık kadar — analytics'in eventual
            # consistent olmasının somut ölçüsü.
            await asyncio.sleep(settings.outbox_poll_seconds)
    finally:
        await publisher.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
