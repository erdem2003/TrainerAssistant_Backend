"""Kafka uretici — outbox relay'in yayin katmani (ADR 0006, Phase 11).

★ NEDEN AYRI MODUL VE AYRI SUREC ★
Yayin, HTTP istek yolunda DEGIL. `POST /v1/workouts` yalnizca veritabanina yazar
(is verisi + outbox satiri, tek transaction); Kafka'ya gonderme isini ayri bir
relay sureci yapar. Kafka yavassa ya da ayakta degilse antrenman kaydi yine de
basarili olur — kullanici antrenmanini kaybetmez. Ters kurgu (istek icinde
publish) Kafka'yi kritik yola sokardi ve outbox deseninin varlik sebebi tam da
bunu engellemek.

★ AT-LEAST-ONCE ★
`mark_published` ile publish AYNI transaction'da degil (olamaz — biri Postgres,
digeri Kafka). Publish basarili olup isaretleme patlarsa ayni olay ikinci kez
yayinlanir. Bu KABUL EDILEN davranis: tuketici `event_id` ile tekrari yutuyor
(service-contract §8). Exactly-once icin dagitik transaction gerekirdi ve bu
olcekte maliyeti faydasini asar.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger(__name__)


class EventPublisher:
    """Tek bir uzun omurlu uretici. Her mesajda yeni baglanti acilmaz."""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap,
            # ★ acks="all" ★
            # Lider TEK BASINA yeterli degil; tum senkron replika yazmadan
            # basarili sayilmiyor. Tek broker'li gelistirme ortaminda fark
            # yaratmaz ama uretimde lider dustugunde olay kaybini engelleyen
            # tek ayar bu ve varsayilani degistirmeyi unutmak kolay.
            acks="all",
            enable_idempotence=True,
            # Yeniden deneme relay dongusunde de var; buradaki, gecici ag
            # hatasinda satiri `attempts` sayacina yazmadan atlatmak icin.
            request_timeout_ms=10_000,
        )
        await self._producer.start()
        logger.info("kafka ureticisi baglandi: %s", settings.kafka_bootstrap)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(
        self,
        topic: str,
        event_id: uuid.UUID,
        event_type: str,
        partition_key: str,
        payload: dict,
        occurred_at: datetime,
    ) -> None:
        """service-contract §8 zarfiyla yayinlar.

        ★ KEY = partition_key = user_id ★
        Ayni kullanicinin olaylari ayni partition'a duser, yani SIRALI kalir.
        Sirasiz olsalardi analytics "antrenman silindi" olayini "antrenman
        eklendi"den once isleyebilirdi.
        """
        if self._producer is None:
            raise RuntimeError("Uretici baslatilmadi: start() cagrilmali")

        envelope = {
            "event_id": str(event_id),
            "event_type": event_type,
            "occurred_at": int(occurred_at.timestamp() * 1000),
            # Outbox satiri correlation_id TASIMIYOR (tabloda kolon yok).
            # Sozlesmede alan opsiyonel; `null` gecmek, uydurmaktan dogru.
            "correlation_id": None,
            "payload": payload,
        }

        await self._producer.send_and_wait(
            topic,
            key=partition_key.encode("utf-8"),
            value=json.dumps(envelope, separators=(",", ":")).encode("utf-8"),
        )


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
