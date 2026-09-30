"""XP defteri — `workout_users/{uid}` kök dokümanı + görev ödülü kayıtları.

    workout_users/{uid}                         {rep_xp, quest_xp, xp_backfilled}
    workout_users/{uid}/quest_claims/{day}_{id} {xp, claimed_at}

`rep_xp` antrenman yazımıyla AYNI transaction'da artıyor (`add_rep_xp_in_tx`).
Bu alan eklenmeden önce antrenman yapmış kullanıcılar için ilk okumada bir kez
tüm geçmiş taranıp değer baştan yazılıyor (`xp_backfilled`).

Görev ödülü `create()` ile: aynı görev iki kez toplanamaz (idempotent).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from app import quests
from app.db import db, user_doc
from app.repo import workouts


REWARD_DURATION = timedelta(hours=24)


@dataclass(frozen=True)
class XpState:
    rep_xp: int
    quest_xp: int
    # Ödüllü reklam (user-service iletir): 24 saat görev XP'si 2 kat / 4. görev.
    xp2x_until: datetime | None = None
    extra_quest_until: datetime | None = None

    def xp2x_active(self, now: datetime) -> bool:
        return self.xp2x_until is not None and self.xp2x_until > now

    def extra_quest_active(self, now: datetime) -> bool:
        return self.extra_quest_until is not None and self.extra_quest_until > now

    @property
    def total(self) -> int:
        return self.rep_xp + self.quest_xp


def add_rep_xp_in_tx(tx, user_id: uuid.UUID, amount: int) -> None:
    tx.set(user_doc(user_id), {"rep_xp": firestore.Increment(amount)}, merge=True)


async def best_form_in_tx(tx, user_id: uuid.UUID, exercise_id: str) -> int | None:
    """Egzersizin kişisel en iyi form puanı (`best_form.{exercise}`). Transaction'da
    YAZIMLARDAN ÖNCE okunmalı (Firestore kuralı)."""
    snap = await user_doc(user_id).get(transaction=tx)
    return ((snap.to_dict() or {}).get("best_form") or {}).get(exercise_id) if snap.exists else None


def set_best_form_in_tx(tx, user_id: uuid.UUID, exercise_id: str, score: int) -> None:
    tx.set(user_doc(user_id), {"best_form": {exercise_id: score}}, merge=True)


def _claim_ref(user_id: uuid.UUID, day: date, quest_id: str):
    return user_doc(user_id).collection("quest_claims").document(f"{day.isoformat()}_{quest_id}")


async def _backfill(user_id: uuid.UUID) -> None:
    total = 0
    query = workouts.workouts_col(user_id).select(["total_reps", "reps_with_errors"])
    async for snap in query.stream():
        data = snap.to_dict()
        total += quests.rep_xp(int(data.get("total_reps", 0)), int(data.get("reps_with_errors", 0)))
    await user_doc(user_id).set({"rep_xp": total, "xp_backfilled": True}, merge=True)


async def get_state(user_id: uuid.UUID) -> XpState:
    snap = await user_doc(user_id).get()
    data = snap.to_dict() if snap.exists else {}
    if not data.get("xp_backfilled"):
        await _backfill(user_id)
        snap = await user_doc(user_id).get()
        data = snap.to_dict() or {}
    return XpState(
        rep_xp=int(data.get("rep_xp", 0)), quest_xp=int(data.get("quest_xp", 0)),
        xp2x_until=data.get("xp2x_until"), extra_quest_until=data.get("extra_quest_until"),
    )


async def grant_reward(user_id: uuid.UUID, reward: str, transaction_id: str, now: datetime) -> bool:
    """`xp2x` / `quest` ödülü: süreyi 24 saat uzatır. `transaction_id` ile idempotent
    (user-service iletimi yeniden denerse ikinci kez verilmez). `True` = yeni verildi."""
    field = {"xp2x": "xp2x_until", "quest": "extra_quest_until"}[reward]
    tx_ref = db.collection("reward_tx").document(transaction_id)

    @firestore.async_transactional
    async def run(tx) -> bool:
        if (await tx_ref.get(transaction=tx)).exists:
            return False
        snap = await user_doc(user_id).get(transaction=tx)
        current = (snap.to_dict() or {}).get(field) if snap.exists else None
        base = current if current is not None and current > now else now
        tx.set(user_doc(user_id), {field: base + REWARD_DURATION}, merge=True)
        tx.create(tx_ref, {"user_id": str(user_id), "reward": reward, "created_at": now})
        return True

    return await run(db.client.transaction())


async def claimed_ids(user_id: uuid.UUID, day: date, quest_ids: list[str]) -> set[str]:
    refs = [_claim_ref(user_id, day, qid) for qid in quest_ids]
    prefix = f"{day.isoformat()}_"
    return {snap.id[len(prefix):] async for snap in db.client.get_all(refs) if snap.exists}


async def claim(user_id: uuid.UUID, day: date, quest_id: str, xp: int) -> bool:
    """`True`: ödül şimdi verildi. `False`: zaten toplanmıştı."""

    @firestore.async_transactional
    async def run(tx) -> bool:
        ref = _claim_ref(user_id, day, quest_id)
        if (await ref.get(transaction=tx)).exists:
            return False
        tx.create(ref, {"xp": xp, "claimed_at": datetime.now(timezone.utc)})
        tx.set(user_doc(user_id), {"quest_xp": firestore.Increment(xp)}, merge=True)
        return True

    try:
        return await run(db.client.transaction())
    except AlreadyExists:
        return False
