"""workout_snapshots — `workout.session` akışının sosyal izdüşümü.

    social_users/{user_id}/snapshots/{workout_id}   snapshot (analytics fact'iyle aynı alanlar)
    social_workout_owners/{workout_id}              {user_id} — küresel sahiplik dizini

Snapshot kullanıcının alt koleksiyonunda: haftalık skor ve meydan okuma
ilerlemesi "kullanıcı X, aralık [a, b)" sorgusu — alt koleksiyonda tek alanlı
`started_at` aralığı, bileşik indeks yok. Sahiplik dizini ise "bu workout_id
kimin" sorusu için (gönderi açma, kudos): Postgres'te `workout_id` birincil
anahtar olduğu için tek satır okumasıydı, burada da tek doküman okuması.

`analytics-service/app/repo/facts.py` ile aynı UPSERT gerekçesi (replay aynı
olaydan güncel mantıkla yeniden üretmeli) ama BAĞIMSIZ kod (ADR 0005).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

from google.cloud import firestore

from app.db import db, user_doc


def snapshot_ref(user_id: uuid.UUID | str, workout_id: uuid.UUID | str):
    return user_doc(user_id).collection("snapshots").document(str(workout_id))


def owner_ref(workout_id: uuid.UUID | str):
    return db.collection("workout_owners").document(str(workout_id))


def upsert_in_tx(tx, *, workout_id: uuid.UUID, user_id: uuid.UUID, data: dict) -> None:
    tx.set(snapshot_ref(user_id, workout_id), {**data, "user_id": str(user_id),
                                               "projected_at": firestore.SERVER_TIMESTAMP})
    tx.set(owner_ref(workout_id), {"user_id": str(user_id)})


async def find_owner(workout_id: uuid.UUID) -> uuid.UUID | None:
    snap = await owner_ref(workout_id).get()
    return uuid.UUID(snap.get("user_id")) if snap.exists else None


async def fetch_between(user_id: uuid.UUID, start_utc: datetime, end_utc: datetime) -> list[dict]:
    query = (
        user_doc(user_id).collection("snapshots")
        .where(filter=firestore.FieldFilter("started_at", ">=", start_utc))
        .where(filter=firestore.FieldFilter("started_at", "<", end_utc))
    )
    return [snap.to_dict() async for snap in query.stream()]


async def fetch_weekly_stats(
    user_ids: list[uuid.UUID],
    start_utc: datetime,
    end_utc: datetime,
    offset_minutes: int,
) -> list[dict]:
    """Faz S5: kullanıcı başına ham bileşenler — puanlama `app/scoring.py`'de.

    `active_days` İZLEYİCİNİN saat dilimiyle: herkes aynı hafta penceresiyle
    karşılaştırılıyor. Yalnızca verisi olan kullanıcılar döner (Postgres'teki
    GROUP BY gibi). Okuma: haftadaki snapshot sayısı (kullanıcılar paralel).
    """
    offset = timedelta(minutes=offset_minutes)
    per_user = await asyncio.gather(*(fetch_between(u, start_utc, end_utc) for u in user_ids))
    rows = []
    for user_id, snaps in zip(user_ids, per_user):
        if not snaps:
            continue
        rows.append({
            "user_id": user_id,
            "total_reps": sum(int(s.get("total_reps", 0)) for s in snaps),
            "clean_reps": sum(max(int(s.get("total_reps", 0)) - int(s.get("reps_with_errors", 0)), 0) for s in snaps),
            "total_sets": sum(int(s.get("total_sets", 0)) for s in snaps),
            "active_days": len({(s["started_at"] + offset).date() for s in snaps}),
        })
    return rows


async def delete_by_user(user_id: uuid.UUID) -> int:
    """Sahiplik dizinini temizler. Snapshot'ların kendisi (ve bildirimler)
    `social_users/{uid}` özyinelemeli silmesiyle gidiyor (routers/internal.py)."""
    query = db.collection("workout_owners").where(filter=firestore.FieldFilter("user_id", "==", str(user_id)))
    count = 0
    async for snap in query.stream():
        await snap.reference.delete()
        count += 1
    return count
