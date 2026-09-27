"""Arkadaşlık — tek kanonik doküman `social_friendships/{low}_{high}`, iki ayrı
istek/kabul kaydı DEĞİL. Gerekçe: ADR 0014 "Sonuçlar" bölümü.

`users: [low, high]` dizisi "bu kullanıcının tüm ilişkileri" sorgusunu tek
alanlı `array-contains` ile karşılıyor (Postgres'teki iki ayrı indeksin yerine).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from google.cloud import firestore

from nabiz_firebase import run_contended_transaction

from app.db import db


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Kanonik sıralama — Postgres'teki CHECK (user_low < user_high)."""
    return (a, b) if str(a) < str(b) else (b, a)


def _ref(a: uuid.UUID, b: uuid.UUID):
    low, high = _pair(a, b)
    return db.collection("friendships").document(f"{low}_{high}")


@dataclass(frozen=True)
class RequestResult:
    status: str
    requested_by: uuid.UUID


async def send_request(requester: uuid.UUID, addressee: uuid.UUID) -> RequestResult:
    """★ TEK TRANSACTION, İKİ SENARYO ★ Doküman yoksa PENDING açılır. Zaten
    PENDING ve FARKLI kişi tarafından istenmişse (karşılıklı istek) ACCEPTED'e
    çevrilir. Aynı anda iki karşılıklı istek gelse de kanonik doküman tek:
    Firestore ikisinden birini yeniden deniyor ve ikinci deneme PENDING'i görüp
    kabul ediyor (Postgres'teki `ON CONFLICT DO UPDATE ... CASE`)."""
    ref = _ref(requester, addressee)
    low, high = _pair(requester, addressee)

    async def run(tx) -> tuple[str, str]:
        snap = await ref.get(transaction=tx)
        if not snap.exists:
            tx.set(ref, {
                "user_low": str(low),
                "user_high": str(high),
                "users": [str(low), str(high)],
                "status": "PENDING",
                "requested_by": str(requester),
                "created_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            return "PENDING", str(requester)
        data = snap.to_dict()
        status, requested_by = data["status"], data["requested_by"]
        if status == "PENDING" and requested_by != str(requester):
            status = "ACCEPTED"
        tx.update(ref, {"status": status, "updated_at": firestore.SERVER_TIMESTAMP})
        return status, requested_by

    status, requested_by = await run_contended_transaction(run)
    return RequestResult(status=status, requested_by=uuid.UUID(requested_by))


async def accept(me: uuid.UUID, requester_id: uuid.UUID) -> bool:
    """Yalnızca BAŞKASININ bana gönderdiği bekleyen isteği kabul eder."""
    ref = _ref(me, requester_id)

    @firestore.async_transactional
    async def run(tx) -> bool:
        snap = await ref.get(transaction=tx)
        if not snap.exists:
            return False
        data = snap.to_dict()
        if data["status"] != "PENDING" or data["requested_by"] == str(me):
            return False
        tx.update(ref, {"status": "ACCEPTED", "updated_at": firestore.SERVER_TIMESTAMP})
        return True

    return await run(db.client.transaction())


async def reject_or_unfriend(a: uuid.UUID, b: uuid.UUID) -> None:
    await _ref(a, b).delete()


async def _all_for(user_id: uuid.UUID) -> list[dict]:
    query = db.collection("friendships").where(
        filter=firestore.FieldFilter("users", "array_contains", str(user_id))
    )
    return [snap.to_dict() async for snap in query.stream()]


def _other(row: dict, user_id: uuid.UUID) -> uuid.UUID:
    return uuid.UUID(row["user_high"] if row["user_low"] == str(user_id) else row["user_low"])


def _newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


async def list_friends(user_id: uuid.UUID) -> list[dict]:
    rows = [r for r in await _all_for(user_id) if r["status"] == "ACCEPTED"]
    return [{"friend_id": _other(r, user_id), "created_at": r["created_at"]} for r in _newest_first(rows)]


async def list_pending(user_id: uuid.UUID) -> tuple[list[dict], list[dict]]:
    """(gelen, giden) — tek sorgudan ikisi birden (Postgres'te iki sorguydu)."""
    incoming, outgoing = [], []
    for r in _newest_first([r for r in await _all_for(user_id) if r["status"] == "PENDING"]):
        other = _other(r, user_id)
        if r["requested_by"] == str(user_id):
            outgoing.append({"addressee_id": other, "created_at": r["created_at"]})
        else:
            incoming.append({"requester_id": other, "created_at": r["created_at"]})
    return incoming, outgoing


async def are_friends(a: uuid.UUID, b: uuid.UUID) -> bool:
    snap = await _ref(a, b).get()
    return snap.exists and snap.get("status") == "ACCEPTED"


async def statuses_with(viewer_id: uuid.UUID, others: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, uuid.UUID]]:
    """Arama sonucu için ilişki durumları — `other -> (status, requested_by)`.
    Postgres'teki LEFT JOIN'in karşılığı: toplu kimlik okuması."""
    if not others:
        return {}
    refs = {_ref(viewer_id, o).id: o for o in others}
    result = {}
    async for snap in db.client.get_all([db.collection("friendships").document(i) for i in refs]):
        if snap.exists:
            data = snap.to_dict()
            result[refs[snap.id]] = (data["status"], uuid.UUID(data["requested_by"]))
    return result


async def delete_all_for_user(user_id: uuid.UUID) -> int:
    query = db.collection("friendships").where(
        filter=firestore.FieldFilter("users", "array_contains", str(user_id))
    )
    count = 0
    async for snap in query.stream():
        await snap.reference.delete()
        count += 1
    return count
