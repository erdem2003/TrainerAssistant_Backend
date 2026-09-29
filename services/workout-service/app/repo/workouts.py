"""Antrenman — `workout_users/{uid}/workouts/{wid}` + küresel kimlik kaydı.

Postgres'teki workouts/sets/reps/rep_form_errors tabloları tek dokümanda
(yerleşim gerekçesi `app/db.py`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from app import formscore
from app.db import db, user_doc

# Liste/istatistik/plan sorgularının çektiği alanlar — setler/tekrarlar HARİÇ.
SUMMARY_FIELDS = [
    "exercise_id",
    "started_at",
    "ended_at",
    "total_sets",
    "total_reps",
    "reps_with_errors",
    "active_seconds",
    "best_set_reps",
    "form_errors",
    "form_score",
]


@dataclass(frozen=True)
class ExistingWorkout:
    user_id: uuid.UUID
    content_hash: str


@dataclass(frozen=True)
class WorkoutSummaryRow:
    id: uuid.UUID
    exercise_id: str
    started_at: datetime
    ended_at: datetime | None
    total_sets: int
    total_reps: int
    reps_with_errors: int
    # Setlerin toplam süresi — setler ARASI dinlenme HARİÇ. Kalori girdisi.
    active_seconds: float
    # Bu antrenmandaki en kalabalık setin tekrar sayısı (kişisel rekor için).
    best_set_reps: int
    # hata türü -> kaç tekrarda görüldü
    form_errors: dict[str, int]
    # 0-100 (`app/formscore.py`); alan eklenmeden önceki antrenmanlarda None.
    form_score: int | None = None


def workouts_col(user_id: uuid.UUID):
    return user_doc(user_id).collection("workouts")


def registry_ref(workout_id: uuid.UUID):
    return db.collection("workout_ids").document(str(workout_id))


def _ms_to_dt(value: int | None) -> datetime | None:
    return None if value is None else datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def build_document(
    *,
    user_id: uuid.UUID,
    exercise_id: str,
    started_at_ms: int,
    ended_at_ms: int | None,
    content_hash: str,
    sets: list,
) -> dict:
    """İstek gövdesinden antrenman dokümanı + önceden hesaplanmış toplamlar.

    Toplamlar Postgres sorgularının birebir karşılığı:
      total_reps       COUNT(reps)
      reps_with_errors en az bir hatası olan tekrar (tekrar başına EN FAZLA bir)
      active_seconds   SUM(set.ended_at - set.started_at) — dinlenme hariç
      best_set_reps    en kalabalık setin tekrar sayısı
      form_errors      hata türü -> tekrar sayısı (rep_form_errors satır sayısı)
    """
    set_docs = []
    form_errors: dict[str, int] = {}
    reps_with_errors = 0
    for s in sorted(sets, key=lambda x: x.index):
        rep_docs = []
        for r in sorted(s.reps, key=lambda x: x.index):
            errors = sorted(set(r.form_errors))
            if errors:
                reps_with_errors += 1
            for error in errors:
                form_errors[error] = form_errors.get(error, 0) + 1
            rep_docs.append(
                {
                    "index": r.index,
                    "duration_seconds": r.duration_seconds,
                    "eccentric_seconds": r.eccentric_seconds,
                    "concentric_seconds": r.concentric_seconds,
                    "rom": r.rom,
                    "form_errors": errors,
                }
            )
        set_docs.append({"index": s.index, "started_at": s.started_at, "ended_at": s.ended_at, "reps": rep_docs})

    return {
        "user_id": str(user_id),
        "exercise_id": exercise_id,
        "started_at": _ms_to_dt(started_at_ms),
        "ended_at": _ms_to_dt(ended_at_ms),
        "content_hash": content_hash,
        "total_sets": len(set_docs),
        "total_reps": sum(len(s["reps"]) for s in set_docs),
        "reps_with_errors": reps_with_errors,
        "active_seconds": sum((s["ended_at"] - s["started_at"]) / 1000.0 for s in set_docs),
        "best_set_reps": max((len(s["reps"]) for s in set_docs), default=0),
        "form_errors": form_errors,
        "form_score": formscore.workout_score(
            [(len(r["form_errors"]), r["rom"]) for s in set_docs for r in s["reps"]]
        ),
        "sets": set_docs,
    }


async def get_existing_in_tx(tx, workout_id: uuid.UUID) -> ExistingWorkout | None:
    snap = await registry_ref(workout_id).get(transaction=tx)
    if not snap.exists:
        return None
    data = snap.to_dict()
    return ExistingWorkout(user_id=uuid.UUID(data["user_id"]), content_hash=data["content_hash"])


def insert_in_tx(tx, workout_id: uuid.UUID, user_id: uuid.UUID, document: dict) -> None:
    """Kimlik kaydı + antrenman. İkisi de `create()`: transaction yarışı
    kaybedilirse Firestore yeniden dener ve bu sefer kayıt görülür
    (Postgres'teki `ON CONFLICT (id) DO NOTHING` yarış dalının karşılığı)."""
    tx.create(
        registry_ref(workout_id),
        {"user_id": str(user_id), "content_hash": document["content_hash"], "created_at": firestore.SERVER_TIMESTAMP},
    )
    tx.create(workouts_col(user_id).document(str(workout_id)), {**document, "created_at": firestore.SERVER_TIMESTAMP})


async def fetch_detail(workout_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    """Antrenmanın tamamı; başkasınınsa (kendi altında yok) `None`."""
    snap = await workouts_col(user_id).document(str(workout_id)).get()
    return snap.to_dict() if snap.exists else None


def _to_summary(snap) -> WorkoutSummaryRow:
    data = snap.to_dict()
    return WorkoutSummaryRow(
        id=uuid.UUID(snap.id),
        exercise_id=data["exercise_id"],
        started_at=data["started_at"],
        ended_at=data.get("ended_at"),
        total_sets=int(data.get("total_sets", 0)),
        total_reps=int(data.get("total_reps", 0)),
        reps_with_errors=int(data.get("reps_with_errors", 0)),
        active_seconds=float(data.get("active_seconds", 0.0)),
        best_set_reps=int(data.get("best_set_reps", 0)),
        form_errors=dict(data.get("form_errors") or {}),
        form_score=data.get("form_score"),
    )


async def fetch_page(
    user_id: uuid.UUID,
    *,
    cursor_started_at: datetime | None,
    cursor_id: uuid.UUID | None,
    limit: int,
) -> list[WorkoutSummaryRow]:
    """En yeni üstte. `(started_at, id)` bileşik imleç — Postgres'teki
    `(w.started_at, w.id) < ($2, $3)` karşılaştırmasının aynısı: aynı anda
    başlamış iki antrenmanda bile kararlı sıra. `__name__` ikincil sıralaması
    tek alanlı indeksin örtük sırası, bileşik indeks gerekmiyor."""
    query = (
        workouts_col(user_id)
        .select(SUMMARY_FIELDS)
        .order_by("started_at", direction=firestore.Query.DESCENDING)
        .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
    )
    if cursor_started_at is not None and cursor_id is not None:
        query = query.start_after({"started_at": cursor_started_at, "__name__": str(cursor_id)})
    return [_to_summary(snap) async for snap in query.limit(limit).stream()]


async def fetch_between(user_id: uuid.UUID, start_utc: datetime, end_utc: datetime) -> list[WorkoutSummaryRow]:
    """`[start, end)` yarım açık aralıktaki antrenmanların özetleri.

    Plan tamamlanması ve günlük istatistiğin ortak kaynağı. Okuma maliyeti:
    aralıktaki antrenman başına 1 doküman.
    """
    query = (
        workouts_col(user_id)
        .select(SUMMARY_FIELDS)
        .where(filter=firestore.FieldFilter("started_at", ">=", start_utc))
        .where(filter=firestore.FieldFilter("started_at", "<", end_utc))
        .order_by("started_at")
    )
    return [_to_summary(snap) async for snap in query.stream()]
