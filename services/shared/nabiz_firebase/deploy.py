"""Dağıtım modu — servis başına Cloud Run (ADR 0020) ya da tek süreç (ADR 0019).

Aynı servis kodu iki biçimde çalışıyor; fark yalnızca ortam değişkenlerinde:

  NABIZ_STANDALONE=1   Servis kendi başına (Cloud Run). Firebase token'ını
                       KENDİSİ doğrular (`install_auth`), olaylar HTTP ile
                       gider (`OUTBOX_HTTP_SUBSCRIBERS`), arka plan döngüleri
                       yerine zamanlayıcı uçları kullanılır.
  (boş)                `gateway/main.py` yedi servisi tek süreçte yükler ve
                       kimliği önde bir kez doğrular (yerel geliştirme).

★ NEDEN ARKA PLAN DÖNGÜSÜ YOK ★ Cloud Run istek yokken CPU vermiyor ve
örneği sıfıra indiriyor; `asyncio` döngüsüne bırakılan iş (outbox yoklaması,
bekleyen gönderi süpürücüsü) ya hiç koşmaz ya da yarıda kalır. Bu yüzden:
  - olay, onu yazan isteğin İÇİNDE dağıtılır (yanıt öncesi arka plan görevi),
  - yeniden deneme ve süpürme Cloud Scheduler'ın çağırdığı `/internal/...`
    uçlarından yapılır.
"""

from __future__ import annotations

import hmac
import json
import logging
import os

import httpx

from nabiz_firebase import outbox

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(20.0)


def standalone() -> bool:
    return os.environ.get("NABIZ_STANDALONE") == "1"


def install_auth(app) -> None:
    """Ayrı dağıtımda Firebase kimlik ara katmanını servisin önüne takar.

    Tek süreçte gateway bunu zaten yapıyor; iki kez takılırsa token iki kez
    doğrulanır (zararsız ama boşa).
    """
    if not standalone():
        return
    from nabiz_firebase.auth import FirebaseAuthMiddleware  # noqa: PLC0415

    app.add_middleware(FirebaseAuthMiddleware)


def internal_key_matches(expected: str, provided: str | None) -> bool:
    """Sabit zamanlı karşılaştırma; tanımsız anahtar HER ZAMAN reddedilir."""
    return bool(expected) and provided is not None and hmac.compare_digest(expected, provided)


def _http_handler(url: str, key: str) -> outbox.Handler:
    async def deliver(envelope: dict) -> None:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(url, json=envelope, headers={"X-Internal-Key": key})
        # 2xx dışı = teslim edilmedi: olay kuyrukta kalır, dağıtıcı yeniden dener.
        response.raise_for_status()

    return deliver


def subscribe_http_from_env(internal_key: str) -> None:
    """`OUTBOX_HTTP_SUBSCRIBERS` → HTTP aboneleri.

    Biçim (JSON): {"<topic>": {"<consumer group>": "<url>"}}
    Grup adları süreç içi abonelikle AYNI tutulmalı: outbox teslim durumunu
    (`delivered`) grup adıyla izliyor, mod değişince olaylar tekrar gitmesin.
    """
    raw = os.environ.get("OUTBOX_HTTP_SUBSCRIBERS")
    if not raw:
        return
    for topic, groups in json.loads(raw).items():
        for group, url in groups.items():
            outbox.subscribe(topic, group, _http_handler(url, internal_key))
