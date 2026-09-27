"""Vücut ölçüsü zaman serisi (B6) — `user_users/{uid}/measurements/{yyyy-MM-dd}`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from app.db import db, user_doc

_FIELDS = ("weight_kg", "waist_cm", "arm_cm")


@dataclass(frozen=True)
class MeasurementRow:
    measured_date: date
    weight_kg: float | None
    waist_cm: float | None
    arm_cm: float | None


def _col(user_id: uuid.UUID):
    return user_doc(user_id).collection("measurements")


def _to_row(day: date, data: dict) -> MeasurementRow:
    return MeasurementRow(
        measured_date=day,
        weight_kg=data.get("weight_kg"),
        waist_cm=data.get("waist_cm"),
        arm_cm=data.get("arm_cm"),
    )


async def upsert(
    user_id: uuid.UUID,
    day: date,
    weight_kg: float | None,
    waist_cm: float | None,
    arm_cm: float | None,
) -> MeasurementRow:
    """Alan bazında birleştirir: boş gelen alan önceki değeri KORUR.

    Postgres'teki `COALESCE(EXCLUDED.x, body_measurements.x)` deseninin
    transaction'lı karşılığı — kullanıcı sabah kiloyu, akşam beli girerse ikinci
    yazım ilkini silmemeli.
    """
    ref = _col(user_id).document(day.isoformat())
    incoming = {"weight_kg": weight_kg, "waist_cm": waist_cm, "arm_cm": arm_cm}

    @firestore.async_transactional
    async def run(tx) -> dict:
        snap = await ref.get(transaction=tx)
        current = (snap.to_dict() or {}) if snap.exists else {}
        merged = {
            field: incoming[field] if incoming[field] is not None else current.get(field)
            for field in _FIELDS
        }
        tx.set(ref, {**merged, "updated_at": firestore.SERVER_TIMESTAMP})
        return merged

    return _to_row(day, await run(db.client.transaction()))


async def fetch_range(user_id: uuid.UUID, start: date, end: date) -> list[MeasurementRow]:
    col = _col(user_id)
    query = (
        col.where(filter=firestore.FieldFilter(FieldPath.document_id(), ">=", col.document(start.isoformat())))
        .where(filter=firestore.FieldFilter(FieldPath.document_id(), "<=", col.document(end.isoformat())))
        .order_by(FieldPath.document_id())
    )
    return [_to_row(date.fromisoformat(s.id), s.to_dict()) async for s in query.stream()]
