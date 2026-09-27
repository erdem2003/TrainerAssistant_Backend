"""Günlük antrenman programı — `workout_users/{uid}/plan/{yyyy-MM-dd}`.

Gün başına TEK doküman, kalemler sıralı bir dizi: `{items: [...]}`. Postgres'te
`(user_id, scheduled_date, exercise_id)` UNIQUE ve `position` kolonu vardı;
burada benzersizlik şemada (PlanDayIn) doğrulanıyor, sıra dizinin kendisi.

Tamamlanma BU DOKÜMANDA TUTULMUYOR (ADR 0012); `done_reps()` ile antrenman
kayıtlarından türetiliyor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from app.db import user_doc
from app.repo import workouts


@dataclass(frozen=True)
class PlanRow:
    id: uuid.UUID
    exercise_id: str
    target_reps: int
    scheduled_time: time | None
    position: int


@dataclass(frozen=True)
class PlanRangeRow:
    scheduled_date: date
    exercise_id: str
    target_reps: int
    scheduled_time: time | None
    position: int


def _col(user_id: uuid.UUID):
    return user_doc(user_id).collection("plan")


def _parse_time(raw: str | None) -> time | None:
    return time.fromisoformat(raw) if raw else None


def _rows(items: list[dict]) -> list[PlanRow]:
    return [
        PlanRow(
            id=uuid.UUID(item["id"]),
            exercise_id=item["exercise_id"],
            target_reps=int(item["target_reps"]),
            scheduled_time=_parse_time(item.get("scheduled_time")),
            position=int(item["position"]),
        )
        for item in sorted(items, key=lambda x: x["position"])
    ]


async def fetch_day(user_id: uuid.UUID, day: date) -> list[PlanRow]:
    snap = await _col(user_id).document(day.isoformat()).get()
    return _rows(snap.get("items") or []) if snap.exists else []


async def fetch_range(user_id: uuid.UUID, start: date, end: date) -> list[PlanRangeRow]:
    col = _col(user_id)
    query = (
        col.where(filter=firestore.FieldFilter(FieldPath.document_id(), ">=", col.document(start.isoformat())))
        .where(filter=firestore.FieldFilter(FieldPath.document_id(), "<=", col.document(end.isoformat())))
        .order_by(FieldPath.document_id())
    )
    result: list[PlanRangeRow] = []
    async for snap in query.stream():
        day = date.fromisoformat(snap.id)
        for row in _rows(snap.get("items") or []):
            result.append(
                PlanRangeRow(
                    scheduled_date=day,
                    exercise_id=row.exercise_id,
                    target_reps=row.target_reps,
                    scheduled_time=row.scheduled_time,
                    position=row.position,
                )
            )
    return result


async def done_reps(user_id: uuid.UUID, start_utc: datetime, end_utc: datetime) -> dict[str, int]:
    """`exercise_id` -> o gün yapılan tekrar sayısı.

    ★ TAMAMLANMANIN TEK KAYNAĞI ★ Gün sınırı PARAMETRE (UTC yarım açık aralık);
    sunucu istemcinin saat dilimini bilmiyor.
    """
    result: dict[str, int] = {}
    for w in await workouts.fetch_between(user_id, start_utc, end_utc):
        result[w.exercise_id] = result.get(w.exercise_id, 0) + w.total_reps
    return result


async def done_reps_by_day(
    user_id: uuid.UUID,
    offset_minutes: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[date, dict[str, int]]:
    """`yerel gün` -> (`exercise_id` -> tekrar). Gün şeridi işaretleri için.

    Gün etiketi UTC zamana saat dilimi farkı EKLENEREK çıkarılıyor —
    Postgres'teki `(started_at AT TIME ZONE 'UTC' + offset)::date`'in aynısı.
    """
    offset = timedelta(minutes=offset_minutes)
    result: dict[date, dict[str, int]] = {}
    for w in await workouts.fetch_between(user_id, start_utc, end_utc):
        local = (w.started_at + offset).date()
        bucket = result.setdefault(local, {})
        bucket[w.exercise_id] = bucket.get(w.exercise_id, 0) + w.total_reps
    return result


async def replace_day(user_id: uuid.UUID, day: date, items: list) -> None:
    """Günün listesini KOMPLE değiştirir.

    Tek dokümanın `set()`'i atomik: Postgres'te "önce sil, sonra ekle" iki adımı
    bir transaction'a sarmak gerekiyordu, burada doğal olarak tek yazım. Boş
    liste dokümanı siler — aralık sorgusu boş günü göstermesin (Postgres'te o
    güne ait satır kalmıyordu).

    Kalem kimlikleri her yazımda YENİ (Postgres'te de sil+ekle yeni UUID
    üretiyordu).
    """
    ref = _col(user_id).document(day.isoformat())
    if not items:
        await ref.delete()
        return
    await ref.set(
        {
            "items": [
                {
                    "id": str(uuid.uuid4()),
                    "exercise_id": item.exercise_id,
                    "target_reps": item.target_reps,
                    "scheduled_time": item.scheduled_time.isoformat() if item.scheduled_time else None,
                    "position": position,
                }
                for position, item in enumerate(items, start=1)
            ],
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
    )
