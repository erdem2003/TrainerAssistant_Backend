"""Soket kayıt defteri + Redis pub/sub köprüsü (ADR 0014, Faz S6).

★ NEDEN REDIS, DOĞRUDAN ÇAĞRI DEĞİL ★
Bir mesaj HTTP'den yazıldığında (app/routers/conversations.py), alıcının
soketi bu süreçte AÇIK OLMAYABİLİR — yatay ölçeklendiğinde başka bir
`chat-service` kopyasında olabilir. `publish()` her zaman Redis'e yazar;
`_subscriber_loop()` HER SÜREÇTE ayrı ayrı dinler ve yalnızca KENDİ yerel
`local_connections`'ında o kullanıcı varsa iletir. Tek süreçli bu ortamda bile
aynı yoldan geçmek — kısayol yok — üretim davranışını burada da doğru
kanıtlıyor (S1'in `20 dakika kesintisiz bağlantı` kanıtıyla aynı disiplin).

WS RECEIVE-ONLY (ADR 0014): istemci bu kanaldan asla YAZMAZ, yalnızca dinler.
Yazma her zaman HTTP'den — `hub.publish()`'i çağıran tek yer HTTP router'ları.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import redis.asyncio as redis
from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "ws:user:"


class Hub:
    def __init__(self) -> None:
        self._local: dict[uuid.UUID, set[WebSocket]] = {}
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._listener_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._redis = redis.from_url(settings.redis_url)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(f"{_CHANNEL_PREFIX}*")
        self._listener_task = asyncio.create_task(self._subscriber_loop())
        logger.info("hub başladı, Redis pub/sub dinleniyor")

    async def stop(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
        if self._pubsub is not None:
            await self._pubsub.close()
        if self._redis is not None:
            await self._redis.close()

    def register(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        self._local.setdefault(user_id, set()).add(websocket)

    def unregister(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        sockets = self._local.get(user_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            del self._local[user_id]

    def is_locally_connected(self, user_id: uuid.UUID) -> bool:
        return bool(self._local.get(user_id))

    async def publish(self, user_id: uuid.UUID, frame: dict) -> None:
        if self._redis is None:
            logger.error("hub.publish çağrıldı ama Redis bağlı değil")
            return
        await self._redis.publish(f"{_CHANNEL_PREFIX}{user_id}", json.dumps(frame))

    async def _subscriber_loop(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message["type"] != "pmessage":
                continue
            try:
                channel = message["channel"].decode()
                user_id = uuid.UUID(channel.removeprefix(_CHANNEL_PREFIX))
            except (ValueError, UnicodeDecodeError):
                logger.error("bozuk kanal adı, atlanıyor: %s", message.get("channel"))
                continue

            sockets = self._local.get(user_id)
            if not sockets:
                continue  # bu kullanıcı bu süreçte bağlı değil — normal.

            raw = message["data"]
            text = raw.decode() if isinstance(raw, bytes) else raw
            # Kapanmış bir soketle karşılaşmak NORMAL: `unregister` disconnect
            # ile pub/sub teslimatı arasında kısa bir yarış olabilir — o
            # soketi listeden düşürüp devam ediyoruz, tüm iletimi iptal etmiyoruz.
            dead = []
            for ws in list(sockets):
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                sockets.discard(ws)


hub = Hub()
