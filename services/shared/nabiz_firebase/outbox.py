"""Firestore outbox + süreç içi dağıtıcı (ADR 0019 karar 2 — Kafka'nın yerine).

★ NE DEĞİŞTİ, NE DEĞİŞMEDİ ★
ADR 0006'nın iki garantisi AYNEN duruyor:
  1. Olay iş verisiyle AYNI transaction'da yazılır (`enqueue(tx, ...)`) —
     "kayıt oldu ama olay gitmedi" durumu yok.
  2. Teslim at-least-once; tüketici tekrarı kendi `processed_events`'iyle yutar.
Değişen yalnızca TAŞIYICI: Kafka topic'i yerine üreticinin `<svc>_outbox`
koleksiyonu, consumer group yerine `subscribe(topic, group, handler)`.

Yerleşim — `<üretici>_outbox/{event_id}`:

    event_id, event_type, topic, partition_key
    occurred_at     epoch ms (zarfın alanı; yazan sürecin saati)
    correlation_id  isteğin kimliği (Kafka dalında hep null'dı)
    payload         olayın gövdesi (Kafka mesajındaki `payload`'ın AYNISI)
    created_at      sunucu zaman damgası — replay sırası
    pending_since   YALNIZCA teslim bekleyen dokümanda var (aşağıya bak)
    delivered       teslim edilen grup adları
    attempts, last_error, dispatched_at, dead_at

★ `pending_since` — BİLEŞİK İNDEKSSİZ BEKLEYEN KUYRUĞU ★
"dispatched == false ORDER BY created_at" bileşik indeks isterdi (üretimde
`firestore.indexes.json` dağıtımı). Onun yerine bekleyen doküman `pending_since`
alanını taşıyor, teslimde alan SİLİNİYOR. Firestore bir alana göre sıralarken o
alanı taşımayan dokümanı zaten döndürmüyor — tek alanlı otomatik indeks yeter,
sorgu yalnızca bekleyenleri ve kronolojik sırayla getirir.

★ OKUMA KOTASI — NEDEN YOKLAMA ARALIĞI UZUN ★
Ücretsiz planda günde 50k okuma var ve BOŞ dönen bir sorgu da 1 okuma sayılıyor:
saniyede bir yoklama günde 86.400 okuma demek — kotanın tamamı. Bu yüzden:
  - `notify()` — yazan istek commit'ten sonra dağıtıcıyı HEMEN uyandırır
    (tek süreç, ADR 0019 karar 1); gecikme milisaniyeler.
  - yoklama yalnızca yedek (varsayılan 60 sn): süreç çöküp yeniden açıldığında
    ya da `notify` kaçtığında bekleyenleri toplar. Günde ~1.440 okuma.

★ SIRA ★ Kafka'da anahtar = user_id ile aynı kullanıcının olayları sıralıydı.
Burada tek dağıtıcı `pending_since` sırasıyla SIRAYLA teslim ediyor; aynı
garanti (ve fazlası — global sıra) korunuyor.

★ BAŞARISIZLIK ★ Bir grubun işleyicisi patlarsa doküman bekleyen kalır,
`attempts` artar; başarılı gruplar `delivered`'a yazıldığı için tekrar
çağrılmaz. `max_attempts`'a ulaşan doküman `dead_at` ile kuyruktan çıkar
(Postgres'teki `attempts < max` filtresinin karşılığı) — `replay()` onu da işler.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from google.cloud import firestore

from nabiz_firebase.firestore import firestore_client

logger = logging.getLogger(__name__)

# Zarf (service-contract §8) → işleyici. Dönüş değeri önemsiz; istisna = başarısız.
Handler = Callable[[dict], Awaitable[object]]

# topic -> grup adı -> işleyici. Consumer group'un süreç içi karşılığı.
_subscribers: dict[str, dict[str, Handler]] = {}


def subscribe(topic: str, group: str, handler: Handler) -> None:
    """Bir tüketici grubunu topic'e bağlar. Aynı grup ikinci kez bağlanırsa
    işleyicisi değişir (yeniden yükleme / test)."""
    _subscribers.setdefault(topic, {})[group] = handler
    logger.info("outbox aboneliği topic=%s group=%s", topic, group)


def unsubscribe(topic: str, group: str) -> None:
    _subscribers.get(topic, {}).pop(group, None)


def subscribers(topic: str) -> dict[str, Handler]:
    return dict(_subscribers.get(topic, {}))


def enqueue(
    tx: firestore.AsyncTransaction,
    collection: firestore.AsyncCollectionReference,
    *,
    event_type: str,
    topic: str,
    partition_key: str,
    payload: dict,
    correlation_id: str | None = None,
    event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Olayı ÇAĞIRANIN transaction'ına ekler — outbox'ın tüm anlamı bu.

    Transaction dışı bir `set()` sürümü BİLEREK yok: iş verisi ile olayın ayrı
    ayrı yazılabildiği bir API, "doğrudan producer.send()" hatasının kapısıdır.
    """
    event_id = event_id or uuid.uuid4()
    tx.create(
        collection.document(str(event_id)),
        {
            "event_id": str(event_id),
            "event_type": event_type,
            "topic": topic,
            "partition_key": partition_key,
            "occurred_at": int(datetime.now(timezone.utc).timestamp() * 1000),
            "correlation_id": correlation_id,
            "payload": payload,
            "created_at": firestore.SERVER_TIMESTAMP,
            "pending_since": firestore.SERVER_TIMESTAMP,
            "delivered": [],
            "attempts": 0,
            "last_error": None,
        },
    )
    return event_id


def envelope_of(data: dict) -> dict:
    """Outbox dokümanı → Kafka mesajındaki zarfın birebir aynısı."""
    return {
        "event_id": data["event_id"],
        "event_type": data["event_type"],
        "occurred_at": data["occurred_at"],
        "correlation_id": data.get("correlation_id"),
        "payload": data["payload"],
    }


class OutboxDispatcher:
    """Tek bir outbox koleksiyonunu aboneleriyle buluşturan süreç içi döngü."""

    def __init__(
        self,
        collection: str,
        *,
        poll_seconds: float = 60.0,
        batch_size: int = 50,
        max_attempts: int = 5,
    ) -> None:
        self.collection_name = collection
        self.poll_seconds = poll_seconds
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        # Aynı süreçte iki tur üst üste binmesin (notify + yoklama).
        self._lock = asyncio.Lock()

    @property
    def collection(self) -> firestore.AsyncCollectionReference:
        return firestore_client().collection(self.collection_name)

    # --- yaşam döngüsü ------------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"outbox:{self.collection_name}")
            logger.info("outbox dağıtıcısı başladı koleksiyon=%s", self.collection_name)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def notify(self) -> None:
        """Yeni olay commit edildi — döngüyü yoklama beklemeden uyandır."""
        self._wake.set()

    async def _run(self) -> None:
        while True:
            try:
                sent = await self.dispatch_pending()
                if sent:
                    logger.info("%d olay dağıtıldı koleksiyon=%s", sent, self.collection_name)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Tek tur patlarsa döngü ÖLMEZ (Kafka relay'indeki kuralın aynısı).
                logger.exception("outbox turu başarısız koleksiyon=%s", self.collection_name)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass
            self._wake.clear()

    # --- dağıtım ------------------------------------------------------------

    async def dispatch_pending(self) -> int:
        """Bekleyen tüm olayları sırayla teslim eder; tamamlanan doküman sayısı."""
        async with self._lock:
            done = 0
            while True:
                query = self.collection.order_by("pending_since").limit(self.batch_size)
                snaps = [snap async for snap in query.stream()]
                if not snaps:
                    return done
                delivered_now = 0
                for snap in snaps:
                    if await self._deliver(snap):
                        delivered_now += 1
                done += delivered_now
                # Tam dolu bir tur hiç ilerleme sağlamadıysa (abonesiz ya da
                # hep patlayan olaylar) aynı turu tekrar sorgulamak kotayı
                # yakmaktan başka işe yaramaz — sonraki uyanışa bırakılır.
                if len(snaps) < self.batch_size or delivered_now == 0:
                    return done

    async def _deliver(self, snap) -> bool:
        data = snap.to_dict()
        topic = data.get("topic")
        groups = subscribers(topic)
        if not groups:
            # Abonesi olmayan olay "teslim edildi" SAYILMAZ: tüketici süreç
            # henüz kaydolmamış olabilir (açılış sırası). Kafka'da da mesaj
            # topic'te kalırdı. Kuyruğun başını tıkamaması için yalnızca bu tur
            # atlanıyor; sonraki turda yeniden bakılır.
            logger.warning("abonesi olmayan topic=%s event_id=%s — bekliyor", topic, snap.id)
            return False

        envelope = envelope_of(data)
        delivered = set(data.get("delivered") or [])
        errors: list[str] = []
        for group, handler in groups.items():
            if group in delivered:
                continue
            try:
                await handler(envelope)
                delivered.add(group)
            except Exception as exc:
                logger.exception("olay işlenemedi group=%s event_id=%s", group, snap.id)
                errors.append(f"{group}: {exc}"[:500])

        if not errors:
            await snap.reference.update(
                {
                    "delivered": sorted(delivered),
                    "pending_since": firestore.DELETE_FIELD,
                    "dispatched_at": firestore.SERVER_TIMESTAMP,
                }
            )
            return True

        attempts = int(data.get("attempts") or 0) + 1
        update = {"delivered": sorted(delivered), "attempts": attempts, "last_error": "; ".join(errors)}
        if attempts >= self.max_attempts:
            # Sonsuz döngü yok: tavanı aşan olay kuyruktan çıkar, iz kalır.
            update["pending_since"] = firestore.DELETE_FIELD
            update["dead_at"] = firestore.SERVER_TIMESTAMP
            logger.error("olay %d denemede işlenemedi, kuyruktan çıktı event_id=%s", attempts, snap.id)
        await snap.reference.update(update)
        return False

    async def replay(self, *, topic: str | None = None, group: str | None = None) -> int:
        """Koleksiyondaki TÜM olayları baştan, `created_at` sırasıyla yeniden verir.

        Kafka'da offset'i sıfırlamanın karşılığı. Teslim durumu değişmez;
        tüketiciler `processed_events` ile tekrarı yutar — gerçekten yeniden
        hesaplatmak isteyen tüketici kendi replay modunu açar (analytics
        `REPLAY_MODE`). `group` verilirse yalnızca o grup çağrılır.
        """
        count = 0
        async for snap in self.collection.order_by("created_at").stream():
            data = snap.to_dict()
            if topic is not None and data.get("topic") != topic:
                continue
            groups = subscribers(data.get("topic"))
            if group is not None:
                groups = {group: groups[group]} if group in groups else {}
            envelope = envelope_of(data)
            for handler in groups.values():
                await handler(envelope)
            count += 1
        return count


_dispatchers: dict[str, OutboxDispatcher] = {}


def dispatcher_for(collection: str, **kwargs) -> OutboxDispatcher:
    """Koleksiyon başına tek dağıtıcı (tek süreçte birden çok servis)."""
    if collection not in _dispatchers:
        _dispatchers[collection] = OutboxDispatcher(collection, **kwargs)
    return _dispatchers[collection]
