"""Ödüllü reklam kazanımları — "Nabız+" ve seri dondurma.

Yerleşim:
    user_users/{uid}/rewards/state   {plus_until, streak_freezes, freeze_days[], daily_count, daily_date}
    user_reward_tx/{transaction_id}  {user_id, reward, status, created_at}  — SSV tekrar koruması

Ödül ve işlem kaydı AYNI transaction'da yazılır: AdMob aynı SSV isteğini tekrar
gönderirse (ağ hatası sonrası yeniden deneme) ödül ikinci kez verilmez.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore

from app.db import db, user_doc

PLUS_DURATION = timedelta(hours=24)
MAX_STREAK_FREEZES = 2
DAILY_REWARD_LIMIT = 10
REWARD_PLUS = "plus"
REWARD_FREEZE = "freeze"
# Etkisi BAŞKA serviste yaşayan ödüller: user-service yalnız SSV'yi doğrular,
# günlük sınırı sayar ve ödülü sahibine iletir (`app/reward_forward.py`).
REWARD_SHIELD = "shield"   # social: bu hafta ligden düşme yok
REWARD_XP2X = "xp2x"       # workout: 24 saat görev XP'si 2 kat
REWARD_QUEST = "quest"     # workout: 24 saat için 4. günlük görev
REMOTE_REWARDS = {REWARD_SHIELD: "social", REWARD_XP2X: "workout", REWARD_QUEST: "workout"}
REWARD_TYPES = {REWARD_PLUS, REWARD_FREEZE, *REMOTE_REWARDS}
_FREEZE_DAYS_KEPT = 60


@dataclass(frozen=True)
class RewardState:
    plus_until: datetime | None
    streak_freezes: int
    freeze_days: list[str]

    def plus_active(self, now: datetime) -> bool:
        return self.plus_until is not None and self.plus_until > now


def _state_ref(user_id: uuid.UUID):
    return user_doc(user_id).collection("rewards").document("state")


def _tx_ref(transaction_id: str):
    return db.collection("reward_tx").document(transaction_id)


def _to_state(data: dict | None) -> RewardState:
    data = data or {}
    return RewardState(
        plus_until=data.get("plus_until"),
        streak_freezes=int(data.get("streak_freezes", 0)),
        freeze_days=list(data.get("freeze_days", [])),
    )


async def get_state(user_id: uuid.UUID) -> RewardState:
    snap = await _state_ref(user_id).get()
    return _to_state(snap.to_dict() if snap.exists else None)


async def grant(user_id: uuid.UUID, reward: str, transaction_id: str, now: datetime) -> str:
    """Ödülü verir. Dönüş: `granted` | `duplicate` | `daily_limit`."""
    state_ref, tx_ref = _state_ref(user_id), _tx_ref(transaction_id)
    today = now.date().isoformat()

    @firestore.async_transactional
    async def run(tx) -> str:
        if (await tx_ref.get(transaction=tx)).exists:
            return "duplicate"
        snap = await state_ref.get(transaction=tx)
        data = snap.to_dict() if snap.exists else {}
        count = int(data.get("daily_count", 0)) if data.get("daily_date") == today else 0
        record = {"user_id": str(user_id), "reward": reward, "created_at": now}
        if count >= DAILY_REWARD_LIMIT:
            tx.create(tx_ref, {**record, "status": "daily_limit"})
            return "daily_limit"

        update: dict = {"daily_count": count + 1, "daily_date": today, "updated_at": now}
        if reward == REWARD_PLUS:
            current = data.get("plus_until")
            base = current if current is not None and current > now else now
            update["plus_until"] = base + PLUS_DURATION
        elif reward == REWARD_FREEZE:
            update["streak_freezes"] = min(int(data.get("streak_freezes", 0)) + 1, MAX_STREAK_FREEZES)
        # REMOTE_REWARDS: etki hedef serviste zaten yazıldı; burada yalnız sayaç + işlem kaydı.
        tx.set(state_ref, update, merge=True)
        tx.create(tx_ref, {**record, "status": "granted"})
        return "granted"

    return await run(db.client.transaction())


async def seen(transaction_id: str) -> bool:
    return (await _tx_ref(transaction_id).get()).exists


async def daily_limit_reached(user_id: uuid.UUID, now: datetime) -> bool:
    snap = await _state_ref(user_id).get()
    data = snap.to_dict() if snap.exists else {}
    return data.get("daily_date") == now.date().isoformat() and int(data.get("daily_count", 0)) >= DAILY_REWARD_LIMIT


def plus_extension(data: dict | None, now: datetime, duration: timedelta) -> datetime:
    """Mevcut Nabız+ süresinin sonuna `duration` ekler (bitmişse şimdiden başlar)."""
    current = (data or {}).get("plus_until")
    base = current if current is not None and current > now else now
    return base + duration


def state_ref(user_id: uuid.UUID):
    return _state_ref(user_id)


async def use_freeze(user_id: uuid.UUID, day: date, now: datetime) -> RewardState | None:
    """`day`'i aktif sayar ve bir hak düşer. Hak yoksa `None`; gün zaten korunmuşsa değişmez."""
    state_ref = _state_ref(user_id)
    key = day.isoformat()

    @firestore.async_transactional
    async def run(tx) -> RewardState | None:
        snap = await state_ref.get(transaction=tx)
        state = _to_state(snap.to_dict() if snap.exists else None)
        if key in state.freeze_days:
            return state
        if state.streak_freezes <= 0:
            return None
        days = sorted({*state.freeze_days, key})[-_FREEZE_DAYS_KEPT:]
        tx.set(state_ref, {"streak_freezes": state.streak_freezes - 1, "freeze_days": days, "updated_at": now}, merge=True)
        return RewardState(state.plus_until, state.streak_freezes - 1, days)

    return await run(db.client.transaction())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
