"""PUT/GET /v1/calibration — kişisel eşik ölçümü, yalnızca saklama (D1).

★ BU UÇ EŞİĞİ DEĞİŞTİRMEZ ★
Ölçülen değerleri kaydeder; canlı rep sayma motoruna (FSM) bağlamaz. Eşik
bağlama kararı `cv-engineer` alanı — CLAUDE.md §6. Bu uç yalnızca "şu değerler
ölçüldü" bilgisini taşır, uygulamanın onu nasıl kullanacağı ayrı bir karar.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header

from app.errors import unprocessable
from app.identity import require_user_id
from app.repo import calibration
from app.schemas import CalibrationIn, CalibrationListOut, CalibrationOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/calibration", tags=["calibration"])

# user-service workout_db'ye erişemez (ADR 0005, database-per-service), o yüzden
# egzersiz kimliği burada sabit listeye karşı doğrulanıyor. Üçü de
# workout-service migration'larındaki katalogla birebir aynı olmalı.
_KNOWN_EXERCISES = {"push_up", "sit_up", "squat"}


def _epoch_ms(value) -> int:
    return int(value.timestamp() * 1000)


def _to_out(row: calibration.CalibrationRow) -> CalibrationOut:
    return CalibrationOut(
        exercise_id=row.exercise_id,
        sample_count=row.sample_count,
        measured_values=row.measured_values,
        calibrated_at=_epoch_ms(row.calibrated_at),
    )


@router.put("/{exercise_id}", response_model=CalibrationOut)
async def put_calibration(
    exercise_id: str,
    payload: CalibrationIn,
    x_user_id: str | None = Header(default=None),
) -> CalibrationOut:
    user_id = require_user_id(x_user_id)
    if exercise_id not in _KNOWN_EXERCISES:
        raise unprocessable("Bilinmeyen egzersiz", {"exercise_id": exercise_id})

    row = await calibration.upsert(
        user_id, exercise_id, payload.sample_count, payload.measured_values
    )

    logger.info(
        "kalibrasyon kaydedildi user_id=%s egzersiz=%s örnek=%d",
        user_id, exercise_id, payload.sample_count,
    )
    return _to_out(row)


@router.get("", response_model=CalibrationListOut)
async def get_all(x_user_id: str | None = Header(default=None)) -> CalibrationListOut:
    user_id = require_user_id(x_user_id)
    rows = await calibration.fetch_all(user_id)
    return CalibrationListOut(profiles=[_to_out(row) for row in rows])
