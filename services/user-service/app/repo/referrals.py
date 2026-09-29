"""Davet et, kazan — davet kodu, davet kaydı ve ödül.

Yerleşim:
    user_referral_codes/{code}     {user_id}                          — kod → davet eden
    user_referrals/{invitee_id}    {inviter_id, status, created_at, completed_at}

Akış: yeni kullanıcı kodu girer (`redeem`) → kayıt `pending`. Davet edilen İLK
antrenmanını bitirince (`WorkoutCompleted` olayı) → `completed` ve iki tarafa da
Nabız+ 3 gün. Ödülü antrenmana bağlamak, sahte hesap açıp kodu kullanarak ödül
toplamayı zorlaştırıyor.

Kod deterministik (kullanıcı kimliğinin özeti): her istekte aynı kod, ayrı bir
"kod üret" adımı yok. Karışan harfler (0/O, 1/I) alfabede yok.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from app.db import db
from app.repo import rewards

REFERRAL_REWARD = timedelta(days=3)
REDEEM_WINDOW = timedelta(days=7)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 7


@dataclass(frozen=True)
class ReferralStats:
    code: str
    invited: int
    completed: int
    referred_by: str | None


class RedeemError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def code_for(user_id: uuid.UUID) -> str:
    digest = hashlib.sha256(f"nabiz-referral:{user_id}".encode()).digest()
    return "".join(_ALPHABET[b % len(_ALPHABET)] for b in digest[:_CODE_LENGTH])


def _codes():
    return db.collection("referral_codes")


def _referrals():
    return db.collection("referrals")


async def ensure_code(user_id: uuid.UUID) -> str:
    code = code_for(user_id)
    try:
        await _codes().document(code).create({"user_id": str(user_id)})
    except AlreadyExists:
        pass
    return code


async def stats(user_id: uuid.UUID) -> ReferralStats:
    code = await ensure_code(user_id)
    base = _referrals().where(filter=firestore.FieldFilter("inviter_id", "==", str(user_id)))
    invited = (await base.count().get())[0][0].value
    completed = 0
    async for snap in base.stream():
        if snap.get("status") == "completed":
            completed += 1
    mine = await _referrals().document(str(user_id)).get()
    return ReferralStats(code, int(invited), completed, mine.get("inviter_id") if mine.exists else None)


async def redeem(invitee_id: uuid.UUID, code: str, profile_created_at: datetime | None, now: datetime) -> str:
    """Kodu kullanır; davet edenin kimliğini döner. Kural ihlalinde `RedeemError`."""
    code = code.strip().upper()
    code_snap = await _codes().document(code).get()
    if not code_snap.exists:
        raise RedeemError("REFERRAL_NOT_FOUND", "Davet kodu bulunamadı")
    inviter_id = code_snap.get("user_id")
    if inviter_id == str(invitee_id):
        raise RedeemError("REFERRAL_SELF", "Kendi davet kodunu kullanamazsın")
    if profile_created_at is not None and now - profile_created_at > REDEEM_WINDOW:
        raise RedeemError("REFERRAL_TOO_LATE", "Davet kodu yalnız ilk 7 gün içinde kullanılabilir")
    try:
        await _referrals().document(str(invitee_id)).create(
            {"inviter_id": inviter_id, "status": "pending", "created_at": now, "completed_at": None}
        )
    except AlreadyExists:
        raise RedeemError("REFERRAL_ALREADY_USED", "Zaten bir davet kodu kullandın") from None
    return inviter_id


async def complete(invitee_id: uuid.UUID, now: datetime) -> bool:
    """Bekleyen daveti tamamlar ve iki tarafa Nabız+ 3 gün verir. Tekrar çağrı zararsız."""
    referral_ref = _referrals().document(str(invitee_id))

    @firestore.async_transactional
    async def run(tx) -> bool:
        snap = await referral_ref.get(transaction=tx)
        if not snap.exists or snap.get("status") != "pending":
            return False
        inviter_id = uuid.UUID(snap.get("inviter_id"))
        refs = [rewards.state_ref(inviter_id), rewards.state_ref(invitee_id)]
        states = [await ref.get(transaction=tx) for ref in refs]  # tüm okumalar yazmadan önce
        for ref, state in zip(refs, states):
            data = state.to_dict() if state.exists else None
            tx.set(ref, {"plus_until": rewards.plus_extension(data, now, REFERRAL_REWARD), "updated_at": now}, merge=True)
        tx.update(referral_ref, {"status": "completed", "completed_at": now})
        return True

    return await run(db.client.transaction())


async def delete_for(user_id: uuid.UUID) -> None:
    """Hesap silme: kişinin kodu ve kendi davet kaydı gider (davet ettiklerininki kalır)."""
    await _codes().document(code_for(user_id)).delete()
    await _referrals().document(str(user_id)).delete()
