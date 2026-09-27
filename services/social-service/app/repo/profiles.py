"""Sosyal profil — `social_profiles/{user_id}` + kullanıcı adı kilidi
`social_usernames/{username_lower}`.

★ KULLANICI ADI TEKLİĞİ ★ Postgres'te `lower(username)` üzerinde UNIQUE indeks
ve `retired_usernames` tablosu vardı. Firestore'da tek bir kilit koleksiyonu
ikisini birden karşılıyor: doküman kimliği küçük harfli ad, içeriği ya sahibi
(`user_id`) ya da emeklilik damgası (`retired_at`). Alma işlemi kilit ve profili
AYNI transaction'da okuyup yazıyor — eşzamanlı iki alım aynı kilidi okuduğu için
Firestore birini yeniden denetiyor ve ikinci deneme kilidi dolu görüp 409 alıyor.

★ YER TUTUCU SATIR YOK ★ Postgres'te ilk çağrıda `social_enabled=false` bir
yer tutucu satır açılıyordu (başka tabloların FK'sız referans verebilmesi için).
Firestore'da profil yalnızca ad alındığında oluşuyor; yer tutucu hiçbir okuma
yolunda görünmüyordu (arama/profil uçları `social_enabled`'ı zaten eliyor).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import firestore

from nabiz_firebase import run_contended_transaction

from app.db import db


class UsernameTaken(Exception):
    """Ad başkasında ya da emekli (hesap silmeyle serbest kalmış)."""


@dataclass(frozen=True)
class SocialProfile:
    user_id: uuid.UUID
    username: str
    display_name: str
    avatar_seed: str
    social_enabled: bool
    created_at: object


def _profiles():
    return db.collection("profiles")


def _lock(username_lower: str):
    return db.collection("usernames").document(username_lower)


def _to_profile(user_id: str, data: dict) -> SocialProfile:
    return SocialProfile(
        user_id=uuid.UUID(user_id),
        username=data["username"],
        display_name=data["display_name"],
        avatar_seed=data["avatar_seed"],
        social_enabled=bool(data.get("social_enabled")),
        created_at=data.get("created_at"),
    )


async def find_by_user_id(user_id: uuid.UUID) -> SocialProfile | None:
    snap = await _profiles().document(str(user_id)).get()
    return _to_profile(snap.id, snap.to_dict()) if snap.exists else None


async def find_by_user_ids(user_ids: list[uuid.UUID]) -> list[SocialProfile]:
    """Toplu okuma — `chat-service`'in konuşma listesi ve feed/yorum yazarları
    için. Okuma maliyeti: benzersiz kimlik sayısı."""
    unique = list(dict.fromkeys(str(u) for u in user_ids))
    if not unique:
        return []
    refs = [_profiles().document(u) for u in unique]
    return [_to_profile(s.id, s.to_dict()) async for s in db.client.get_all(refs) if s.exists]


async def profiles_map(user_ids) -> dict[uuid.UUID, SocialProfile]:
    return {p.user_id: p for p in await find_by_user_ids(list(user_ids))}


async def claim_username(user_id: uuid.UUID, username: str, display_name: str) -> SocialProfile:
    """Sosyali açar: adı alır, `social_enabled=true` yapar. Aynı kullanıcı aynı
    adı tekrar alırsa idempotent; farklı ada geçerse eski ad serbest kalır
    (Postgres'teki `UPDATE ... SET username` ile aynı — eski ad emekliye
    ayrılmıyordu, yalnızca hesap silmede ayrılıyor)."""
    lower = username.lower()
    prof_ref = _profiles().document(str(user_id))
    now = datetime.now(timezone.utc)

    async def run(tx) -> dict:
        lock_snap = await _lock(lower).get(transaction=tx)
        prof_snap = await prof_ref.get(transaction=tx)
        if lock_snap.exists:
            lock = lock_snap.to_dict()
            if lock.get("retired_at") is not None or lock.get("user_id") != str(user_id):
                raise UsernameTaken(username)
        current = prof_snap.to_dict() if prof_snap.exists else {}
        old_lower = current.get("username_lower")
        if old_lower and old_lower != lower:
            tx.delete(_lock(old_lower))
        tx.set(_lock(lower), {"user_id": str(user_id), "claimed_at": now})
        data = {
            "username": username,
            "username_lower": lower,
            "display_name": display_name,
            "avatar_seed": current.get("avatar_seed") or str(user_id),
            "social_enabled": True,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
        }
        tx.set(prof_ref, data)
        return data

    # Kilit sıcak bir doküman olabilir (popüler ad): jitterli yeniden deneme,
    # yarışı kaybeden 500 değil 409 alsın diye.
    data = await run_contended_transaction(run)
    return _to_profile(str(user_id), data)


async def search(query: str, limit: int, viewer_id: uuid.UUID) -> list[SocialProfile]:
    """Önek araması (`lower(username) LIKE q%`), kendisi hariç, ada göre sıralı.

    Tek alanlı aralık sorgusu `username_lower` üzerinde; izleyiciyi elemek
    için bir fazla çekiliyor. Sıralama küçük harfli ada göre (Postgres'te
    büyük/küçük harf duyarlı `ORDER BY username` idi — yalnızca karışık harfli
    adların sırası farklılaşabilir).
    """
    q = query.lower()
    stream = (
        _profiles()
        .where(filter=firestore.FieldFilter("username_lower", ">=", q))
        .where(filter=firestore.FieldFilter("username_lower", "<", q + ""))
        .order_by("username_lower")
        .limit(limit + 1)
        .stream()
    )
    result = []
    async for snap in stream:
        profile = _to_profile(snap.id, snap.to_dict())
        if profile.user_id == viewer_id or not profile.social_enabled:
            continue
        result.append(profile)
    return result[:limit]


async def delete_and_retire(user_id: uuid.UUID) -> None:
    """Hesap silme: profili siler, adın kilidini EMEKLİ olarak bırakır —
    yeni bir hesap eski sosyal kimliği devralamasın (ADR 0014, Sonuçlar).

    Postgres'teki `retired_usernames` gibi süresiz: şemadaki "30 gün" yorumunu
    uygulayan bir temizlik işi orada da yoktu.
    """
    prof_ref = _profiles().document(str(user_id))
    snap = await prof_ref.get()
    if snap.exists:
        lower = snap.get("username_lower")
        await _lock(lower).set({"retired_at": firestore.SERVER_TIMESTAMP})
    await prof_ref.delete()
