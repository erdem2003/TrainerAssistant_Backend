"""PUT/GET /v1/measurements — vücut ölçüsü zaman serisi (B6)."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Header, Query

from app.db import db
from app.errors import unprocessable
from app.identity import require_user_id
from app.repo import measurements
from app.schemas import MeasurementIn, MeasurementOut, MeasurementRangeOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/measurements", tags=["measurements"])

_MAX_RANGE_DAYS = 400


def _parse_date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise unprocessable(
            "Tarih YYYY-AA-GG biçiminde olmalı", {"field": field}
        ) from None


@router.put("", response_model=MeasurementOut)
async def set_measurement(
    payload: MeasurementIn,
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
) -> MeasurementOut:
    """Bir günün ölçümünü ayarlar. Boş alanlar önceki değeri korur."""
    user_id = require_user_id(x_user_id)
    target = _parse_date(day, "date")

    if payload.weight_kg is None and payload.waist_cm is None and payload.arm_cm is None:
        raise unprocessable("En az bir ölçü değeri gerekli")

    async with db.pool.acquire() as conn:
        row = await measurements.upsert(
            conn, user_id, target, payload.weight_kg, payload.waist_cm, payload.arm_cm
        )

    logger.info("ölçüm kaydedildi user_id=%s gün=%s", user_id, target)
    return MeasurementOut(
        date=row.measured_date.isoformat(),
        weight_kg=row.weight_kg,
        waist_cm=row.waist_cm,
        arm_cm=row.arm_cm,
    )


@router.get("/range", response_model=MeasurementRangeOut)
async def get_range(
    x_user_id: str | None = Header(default=None),
    start_day: str = Query(alias="from"),
    end_day: str = Query(alias="to"),
) -> MeasurementRangeOut:
    """Aralıktaki ölçümler — YALNIZCA kaydı olan günler döner."""
    user_id = require_user_id(x_user_id)
    first = _parse_date(start_day, "from")
    last = _parse_date(end_day, "to")

    if last < first:
        raise unprocessable("Bitiş tarihi başlangıçtan önce olamaz")
    if (last - first).days + 1 > _MAX_RANGE_DAYS:
        raise unprocessable("Aralık çok geniş", {"max_days": _MAX_RANGE_DAYS})

    async with db.pool.acquire() as conn:
        rows = await measurements.fetch_range(conn, user_id, first, last)

    return MeasurementRangeOut(
        entries=[
            MeasurementOut(
                date=row.measured_date.isoformat(),
                weight_kg=row.weight_kg,
                waist_cm=row.waist_cm,
                arm_cm=row.arm_cm,
            )
            for row in rows
        ]
    )
