"""Kişisel eşik ölçümü (D1) — `user_users/{uid}/calibration/{exercise_id}`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.db import user_doc


@dataclass(frozen=True)
class CalibrationRow:
    exercise_id: str
    sample_count: int
    measured_values: dict[str, float]
    calibrated_at: datetime


def _col(user_id: uuid.UUID):
    return user_doc(user_id).collection("calibration")


def _to_row(exercise_id: str, data: dict) -> CalibrationRow:
    return CalibrationRow(
        exercise_id=exercise_id,
        sample_count=int(data["sample_count"]),
        measured_values={k: float(v) for k, v in data["measured_values"].items()},
        calibrated_at=data["calibrated_at"],
    )


async def upsert(
    user_id: uuid.UUID,
    exercise_id: str,
    sample_count: int,
    measured_values: dict[str, float],
) -> CalibrationRow:
    """Egzersiz başına tek doküman; yeni ölçüm eskisinin TAMAMEN yerine geçer
    (Postgres'teki `ON CONFLICT DO UPDATE SET ... = EXCLUDED`) — `set()`
    zaten bu anlamda, transaction gerekmiyor."""
    data = {
        "sample_count": sample_count,
        "measured_values": measured_values,
        "calibrated_at": datetime.now(timezone.utc),
    }
    await _col(user_id).document(exercise_id).set(data)
    return _to_row(exercise_id, data)


async def fetch_one(user_id: uuid.UUID, exercise_id: str) -> CalibrationRow | None:
    snap = await _col(user_id).document(exercise_id).get()
    return _to_row(exercise_id, snap.to_dict()) if snap.exists else None


async def fetch_all(user_id: uuid.UUID) -> list[CalibrationRow]:
    # Doküman kimliği = exercise_id; varsayılan sıralama kimliğe göre
    # (Postgres'teki `ORDER BY exercise_id`).
    return [_to_row(s.id, s.to_dict()) async for s in _col(user_id).stream()]
