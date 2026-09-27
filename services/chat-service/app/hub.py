"""Süreç içi soket kayıt defteri — canlı ortak antrenman rölesi (ADR 0014 Faz S7).

★ REDIS PUB/SUB KALKTI (ADR 0019) ★ Postgres dalında hub her mesajı Redis'e
yazıp HER süreçte dinliyordu (yatay ölçek için). Dağıtım artık TEK süreç
(ADR 0019 karar 1): alıcının soketi ya bu süreçtedir ya hiç yoktur, Redis
köprüsü yalnızca gecikme ekliyordu. `publish()` doğrudan yerel soketlere iletir.

★ KİM HÂLÂ KULLANIYOR ★ Yalnızca canlı ortak antrenman (`routers/live.py` —
SESSION_INVITE/JOINED/PROGRESS/ENDED). Sohbet mesajı (MESSAGE), okundu (RECEIPT)
ve sosyal bildirim (NOTIFICATION) çerçeveleri artık gönderilmiyor: üçü de
Firestore dokümanı olarak yazılıyor ve mobil snapshot dinleyicisiyle okuyor.

WS RECEIVE-ONLY (ADR 0014): istemci bu kanaldan asla YAZMAZ.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._local: dict[uuid.UUID, set[WebSocket]] = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self._local.clear()

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
        """Bağlı değilse sessizce düşer — röle kalıcı değil (Faz S7 kararı)."""
        sockets = self._local.get(user_id)
        if not sockets:
            return
        text = json.dumps(frame)
        # Kapanmış bir soketle karşılaşmak NORMAL (disconnect ile iletim
        # arasında yarış) — o soketi düşürüp devam ediliyor.
        dead = []
        for ws in list(sockets):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            sockets.discard(ws)


hub = Hub()
