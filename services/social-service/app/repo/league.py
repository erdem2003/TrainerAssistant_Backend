"""Haftalık lig — üyelik, gruplar ve katman durumu.

    social_league_state/{user_id}           {tier, week, last_result}
    social_league_members/{week}_{user_id}  {user_id, week, tier, group_id}
    social_league_groups/{group_id}         {week, tier, members: [...], size}   group_id = {week}_{tier}_{n}
    social_league_open/{week}_{tier}        {group_id, seq, size} — dolmakta olan grup işaretçisi

Tamamı doküman kimliğiyle erişiliyor: bileşik indeks yok (bkz. `app/db.py`).
Puan ve sıra SAKLANMIYOR — her okumada grubun snapshot'larından hesaplanıyor
(ADR 0012'nin çizgisi); saklanan yalnız "kim hangi grupta ve hangi katmanda".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from google.cloud import firestore

from app import league, scoring
from app.db import db
from app.repo import snapshots


@dataclass(frozen=True)
class Standing:
    rank: int
    breakdown: scoring.ScoreBreakdown


@dataclass(frozen=True)
class Membership:
    week: date
    tier: str
    group_id: str
    last_result: dict | None


def _state_ref(user_id: uuid.UUID):
    return db.collection("league_state").document(str(user_id))


def _member_ref(week: date, user_id: uuid.UUID):
    return db.collection("league_members").document(f"{week.isoformat()}_{user_id}")


def _group_ref(group_id: str):
    return db.collection("league_groups").document(group_id)


def _open_ref(week: date, tier: str):
    return db.collection("league_open").document(f"{week.isoformat()}_{tier}")


async def group_standings(group_id: str) -> tuple[dict, list[Standing]]:
    """Grubun o haftaki sıralaması. Eşitlikte temiz tekrar, sonra kimlik (kararlı)."""
    snap = await _group_ref(group_id).get()
    group = snap.to_dict() or {}
    members = [uuid.UUID(m) for m in group.get("members", [])]
    week = date.fromisoformat(group["week"]) if group.get("week") else None
    if not members or week is None:
        return group, []
    start = league.week_end_utc(week - timedelta(days=7))
    end = league.week_end_utc(week)
    rows = {r["user_id"]: r for r in await snapshots.fetch_weekly_stats(
        members, start, end, league.LEAGUE_OFFSET_MINUTES)}
    breakdowns = [
        scoring.compute(
            m,
            total_reps=rows[m]["total_reps"] if m in rows else 0,
            clean_reps=rows[m]["clean_reps"] if m in rows else 0,
            total_sets=rows[m]["total_sets"] if m in rows else 0,
            active_days=rows[m]["active_days"] if m in rows else 0,
        )
        for m in members
    ]
    breakdowns.sort(key=lambda b: (-b.score, -b.clean_reps, str(b.user_id)))
    return group, [Standing(rank=i, breakdown=b) for i, b in enumerate(breakdowns, start=1)]


async def _result_of(user_id: uuid.UUID, week: date, shielded: bool = False) -> dict | None:
    member = await _member_ref(week, user_id).get()
    if not member.exists:
        return None
    group_id = member.get("group_id")
    tier = member.get("tier")
    _, standings = await group_standings(group_id)
    mine = next((s for s in standings if s.breakdown.user_id == user_id), None)
    if mine is None:
        return None
    return {
        "week": week.isoformat(),
        "tier_before": tier,
        "tier_after": _apply_shield(tier, league.next_tier(tier, mine.rank, len(standings), mine.breakdown.score), shielded),
        "shielded": shielded,
        "rank": mine.rank,
        "group_size": len(standings),
        "score": mine.breakdown.score,
    }


async def ensure_member(user_id: uuid.UUID, week: date) -> Membership:
    """Kullanıcıyı bu haftanın bir grubuna yerleştirir (zaten varsa dokunmaz).

    Katman: ilk kez → Bronz; geçen hafta oynadıysa o grubun sonucu; daha uzun
    ara → bir katman aşağı.
    """
    existing = await _member_ref(week, user_id).get()
    state_snap = await _state_ref(user_id).get()
    state = state_snap.to_dict() if state_snap.exists else None
    if existing.exists:
        return Membership(week, existing.get("tier"), existing.get("group_id"),
                          (state or {}).get("last_result"))

    tier, last_result = league.TIERS[0], None
    if state and state.get("week"):
        previous_week = date.fromisoformat(state["week"])
        if previous_week == week - timedelta(days=7):
            shielded = state.get("shield_week") == previous_week.isoformat()
            last_result = await _result_of(user_id, previous_week, shielded)
            tier = last_result["tier_after"] if last_result else state.get("tier", tier)
        elif previous_week < week:
            tier = league.after_absence(state.get("tier", tier))
        else:
            tier = state.get("tier", tier)

    @firestore.async_transactional
    async def join(tx) -> str:
        member_ref = _member_ref(week, user_id)
        member = await member_ref.get(transaction=tx)
        if member.exists:  # eşzamanlı ikinci istek kazandı
            return member.get("group_id")
        open_ref = _open_ref(week, tier)
        pointer = await open_ref.get(transaction=tx)
        data = pointer.to_dict() if pointer.exists else None
        if data is None or int(data.get("size", 0)) >= league.GROUP_SIZE:
            seq = int(data.get("seq", 0)) + 1 if data else 1
            group_id = f"{week.isoformat()}_{tier}_{seq}"
            tx.set(_group_ref(group_id), {"week": week.isoformat(), "tier": tier,
                                          "members": [str(user_id)], "size": 1})
            tx.set(open_ref, {"group_id": group_id, "seq": seq, "size": 1})
        else:
            group_id = data["group_id"]
            tx.update(_group_ref(group_id), {"members": firestore.ArrayUnion([str(user_id)]),
                                             "size": firestore.Increment(1)})
            tx.update(open_ref, {"size": firestore.Increment(1)})
        tx.set(member_ref, {"user_id": str(user_id), "week": week.isoformat(),
                            "tier": tier, "group_id": group_id})
        tx.set(_state_ref(user_id), {"tier": tier, "week": week.isoformat(), "last_result": last_result})
        return group_id

    group_id = await join(db.client.transaction())
    return Membership(week, tier, group_id, last_result)


def _apply_shield(before: str, after: str, shielded: bool) -> str:
    """Kalkan (ödüllü reklam): o hafta düşme yok — terfi etkilenmez."""
    if shielded and league.tier_index(after) < league.tier_index(before):
        return before
    return after


async def is_shielded(user_id: uuid.UUID, week: date) -> bool:
    snap = await _state_ref(user_id).get()
    return snap.exists and (snap.to_dict() or {}).get("shield_week") == week.isoformat()


async def grant_shield(user_id: uuid.UUID, transaction_id: str, week: date) -> bool:
    """Bu hafta için düşme kalkanı. `transaction_id` ile idempotent. `True` = yeni verildi."""
    tx_ref = db.collection("reward_tx").document(transaction_id)

    @firestore.async_transactional
    async def run(tx) -> bool:
        if (await tx_ref.get(transaction=tx)).exists:
            return False
        tx.set(_state_ref(user_id), {"shield_week": week.isoformat()}, merge=True)
        tx.create(tx_ref, {"user_id": str(user_id), "reward": "shield", "week": week.isoformat()})
        return True

    return await run(db.client.transaction())


async def delete_for(user_id: uuid.UUID) -> None:
    """Hesap silme: durum + üyelikler. Grup listesinde kalan kimlik okumada
    atlanır (profil yok)."""
    await _state_ref(user_id).delete()
    query = db.collection("league_members").where(filter=firestore.FieldFilter("user_id", "==", str(user_id)))
    async for snap in query.stream():
        await snap.reference.delete()
