"""GET /ws — tek gercek zamanli baglanti: sohbet mesajlari + sosyal bildirimler.

TEK DOGRULUK KAYNAGI: ADR 0014 "Soket omru ve token suresi" bolumu.

★ BU SERVIS JWT COZMEZ ★
Kimlik dogrulama gateway'de bitiyor (service-contract §2). `X-User-Id` ve
`X-Token-Exp` basliklari, gateway'in `/internal/verify-token` alt-istegine
auth-service'in verdigi yanittan geliyor (`auth-service/app/routers/
identity.py`). Bu servis o iki degeri OLDUGU GIBI kullanir, hicbir JWT
kutuphanesi bu pyproject.toml'da yok.

★ SOKET NEDEN SINIRLI OMURLU ★
`auth_request` yalnizca EL SIKISMADA calisiyor (nginx bir daha kimlik
dogrulamiyor). Erisim token'i 15 dakikada bir doluyor. Token'in bitis zamani
`X-Token-Exp`'ten okunup soket o ana geldiginde 4401 ile KAPATILIYOR.
Istemci bu ani `HELLO` cercevesinden once biliyor ve -60sn'de yeni soketi
ACIP sonra eskisini kapatiyor (ADR 0014) — kesinti sifir.

★ FAZ S6 GÜNCELLEMESİ ★ Soket artık `app/hub.py`'ye KAYDEDİLİYOR — HTTP'den
gelen bir mesaj (`app/routers/conversations.py`) Redis üzerinden buraya
düşüyor. İstemciden gelen metin çerçeveleri YOK SAYILIYOR (loglanıp atılıyor):
protokol RECEIVE-ONLY (ADR 0014) — yazma her zaman HTTP'den, S1'in echo'su
kaldırıldı.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.hub import hub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

# nginx `/ws` location'inin auth_request_set ile yazdigi basliklar.
HEADER_USER_ID = "x-user-id"
HEADER_TOKEN_EXP = "x-token-exp"

# ★ KAPANIS KODLARI ★
# 4000-4999 uygulama-tanimli aralik (RFC 6455). 4401, HTTP 401'in soket
# karsiligi: "token suresi doldu, yeniden bagla".
CLOSE_TOKEN_EXPIRED = 4401


def _now_ms() -> int:
    return int(time.time() * 1000)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    user_id_raw = websocket.headers.get(HEADER_USER_ID)
    token_exp_raw = websocket.headers.get(HEADER_TOKEN_EXP)

    if not user_id_raw:
        # Gateway'siz dogrudan baglanti denemesi. Uretimde ulasilmaz olmali —
        # `chat-service` compose agi disina hic acilmiyor.
        await websocket.close(code=4401)
        return

    try:
        user_id = uuid.UUID(user_id_raw)
    except ValueError:
        await websocket.close(code=4401)
        return

    # `X-Token-Exp` epoch MILISANIYE (service-contract §6). Ayristirilamiyorsa
    # sunucu tarafi ust sinirla (WS_MAX_LIFETIME) devam edilir — soket
    # SONSUZA KADAR acik kalmaz, yalnizca daha erken kapanmaz.
    try:
        expires_at_ms = int(token_exp_raw) if token_exp_raw else None
    except ValueError:
        expires_at_ms = None

    hard_deadline_ms = _now_ms() + settings.ws_max_lifetime_seconds * 1000
    deadline_ms = min(expires_at_ms, hard_deadline_ms) if expires_at_ms else hard_deadline_ms

    await websocket.accept()
    logger.info("soket acildi user_id=%s deadline_ms=%s", user_id, deadline_ms)

    await websocket.send_text(json.dumps({
        "type": "HELLO",
        "user_id": str(user_id),
        "expires_at": deadline_ms,
        "server_time": _now_ms(),
    }))

    hub.register(user_id, websocket)
    closer = asyncio.create_task(_close_at_deadline(websocket, deadline_ms))
    try:
        while True:
            # RECEIVE-ONLY protokol (ADR 0014): istemci bu kanaldan asla
            # YAZMAZ. Bir metin çerçevesi gelirse (beklenmedik istemci/hata)
            # yok sayılır — döngü yalnızca disconnect'i beklemek için var.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("soket kapandı user_id=%s", user_id)
    finally:
        hub.unregister(user_id, websocket)
        closer.cancel()


async def _close_at_deadline(websocket: WebSocket, deadline_ms: int) -> None:
    """Token suresi dolunca (ya da sunucu ust siniri gelince) sokete el atar."""
    remaining_s = max(0.0, (deadline_ms - _now_ms()) / 1000.0)
    try:
        await asyncio.sleep(remaining_s)
        await websocket.close(code=CLOSE_TOKEN_EXPIRED)
    except asyncio.CancelledError:
        # Baglanti zaten normal yoldan kapandi (istemci ayrildi) — bu
        # gorevin isi bitti, yeniden kapatmaya calismak hataya yol acar.
        pass
