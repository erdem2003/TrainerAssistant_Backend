"""Push bildirimi cihaz kayıtları (FCM registration token).

Yerleşim:
    user_devices/{sha256(token)[:40]}   {token, user_id, platform, updated_at}

★ NEDEN KÖK KOLEKSİYON, KULLANICI ALTINDA DEĞİL ★ Aynı telefonda çıkış yapıp
başka hesapla girilince FCM token'ı DEĞİŞMİYOR. Kayıt kullanıcı altında olsaydı
token iki hesapta birden kalır, eski hesabın bildirimleri yeni kullanıcıya
giderdi. Doküman kimliği token'ın özeti: yeni kayıt `user_id`'yi üzerine yazar,
token kendiliğinden yeni sahibine taşınır.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from google.cloud import firestore

from app.db import db

MAX_DEVICES_PER_USER = 10


def _col():
    return db.collection("devices")


def _doc_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:40]


async def register(user_id: uuid.UUID, token: str, platform: str, now: datetime) -> None:
    await _col().document(_doc_id(token)).set(
        {"token": token, "user_id": str(user_id), "platform": platform, "updated_at": now}
    )


async def unregister(user_id: uuid.UUID, token: str) -> None:
    """Yalnız kendi kaydını siler — başkasının token'ını kaldıramazsın."""
    ref = _col().document(_doc_id(token))
    snap = await ref.get()
    if snap.exists and snap.get("user_id") == str(user_id):
        await ref.delete()


async def tokens_for(user_id: uuid.UUID) -> list[str]:
    query = (
        _col()
        .where(filter=firestore.FieldFilter("user_id", "==", str(user_id)))
        .limit(MAX_DEVICES_PER_USER)
    )
    return [snap.get("token") async for snap in query.stream()]


async def remove_tokens(tokens: list[str]) -> None:
    """FCM'in geçersiz dediği token'lar (uygulama kaldırıldı, token yenilendi)."""
    for token in tokens:
        await _col().document(_doc_id(token)).delete()


async def delete_for(user_id: uuid.UUID) -> None:
    query = _col().where(filter=firestore.FieldFilter("user_id", "==", str(user_id)))
    async for snap in query.stream():
        await snap.reference.delete()
