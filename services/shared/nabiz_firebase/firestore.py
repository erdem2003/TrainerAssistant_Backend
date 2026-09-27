"""Firestore async istemcisi — tek süreçte tek örnek.

KİMLİK BİLGİSİ SIRASI:
1. `FIRESTORE_EMULATOR_HOST` varsa emülatör (testler); kimlik gerekmez.
2. `FIREBASE_SERVICE_ACCOUNT_JSON` ortam değişkeni (Render'da dosya yok, gizli
   değişken var) — JSON metni.
3. Yoksa Application Default Credentials (`GOOGLE_APPLICATION_CREDENTIALS`).

DATABASE-PER-SERVICE KARŞILIĞI: her servis yalnızca kendi kök koleksiyonuna
dokunur (`FirestoreDatabase(root="health")` → `health_users/...`). Başka servisin
koleksiyonunu okumak yasak; veri olaylarla (outbox) akar — Postgres'teki
"her servisin kendi veritabanı" kuralının aynısı.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from google.api_core.exceptions import Aborted
from google.cloud import firestore

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def run_contended_transaction(
    fn: Callable[[firestore.AsyncTransaction], Awaitable[T]],
    *,
    attempts_per_round: int = 5,
    rounds: int = 6,
) -> T:
    """Aynı dokümana yarışan transaction'lar için JİTTERLİ yeniden deneme.

    `@async_transactional` iptal edilen (ABORTED) bir transaction'ı ARA
    VERMEDEN yeniden deniyor; sunucu SDK'sı kilitli (pessimistic) okuduğu için
    aynı dokümanı okuyan N eşzamanlı transaction ardışık kilit zaman aşımına
    düşüp denemelerini tüketebiliyor. Turlar arasına rastgele, üstel artan bir
    bekleme koymak yarışanları zamana yayıyor. Yalnızca gerçek bir yarış
    beklenen yerlerde (kullanıcı adı kilidi, kanonik arkadaşlık çifti)
    kullanılıyor; `fn` içinden fırlatılan iş istisnaları (409/404) aynen geçer.
    """
    wrapped = firestore.async_transactional(fn)
    for round_no in range(rounds):
        try:
            return await wrapped(firestore_client().transaction(max_attempts=attempts_per_round))
        except (Aborted, ValueError) as exc:
            # ValueError yalnızca "Failed to commit transaction in N attempts"
            # ise yarış; başka bir ValueError iş mantığınındır, yutulmaz.
            if isinstance(exc, ValueError) and "Failed to commit transaction" not in str(exc):
                raise
            if round_no == rounds - 1:
                raise
            await asyncio.sleep(random.uniform(0.05, 0.2) * (2**round_no))
    raise AssertionError("ulaşılamaz")

DEFAULT_PROJECT = "nabiz-trainer"

_client: firestore.AsyncClient | None = None


def firestore_client() -> firestore.AsyncClient:
    global _client
    if _client is None:
        project = os.environ.get("FIREBASE_PROJECT_ID", DEFAULT_PROJECT)
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        if raw and not os.environ.get("FIRESTORE_EMULATOR_HOST"):
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_info(json.loads(raw))
            _client = firestore.AsyncClient(project=project, credentials=credentials)
        else:
            _client = firestore.AsyncClient(project=project)
        logger.info("firestore istemcisi açıldı project=%s emulator=%s", project, os.environ.get("FIRESTORE_EMULATOR_HOST"))
    return _client


class FirestoreDatabase:
    """Servisin Firestore görünümü. asyncpg `Database`'in yerini alır.

    `connect/close/migrate` korunuyor ki servis `main.py`'lerinin yaşam döngüsü
    aynı kalsın; Firestore'da şema yok, `migrate` bilerek boş.
    """

    def __init__(self, root: str) -> None:
        self.root = root

    @property
    def client(self) -> firestore.AsyncClient:
        return firestore_client()

    def collection(self, name: str) -> firestore.AsyncCollectionReference:
        """`<servis>_<ad>` kök koleksiyonu."""
        return self.client.collection(f"{self.root}_{name}")

    async def connect(self) -> None:
        firestore_client()

    async def close(self) -> None:
        # İstemci süreç boyunca paylaşılıyor (tek süreçte birden çok servis).
        return None

    async def migrate(self) -> None:
        return None

    async def healthy(self) -> bool:
        try:
            # En ucuz okuma: var olmayabilen tek doküman. Ağ + kimlik doğrulanır.
            await self.collection("health").document("ping").get()
            return True
        except Exception:
            logger.exception("firestore sağlık kontrolü başarısız")
            return False
