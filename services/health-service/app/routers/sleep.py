"""GET/PUT/DELETE /v1/sleep — gecelik uyku suresi (ADR 0010)."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Header, Query, Response, status

from app.db import db
from app.errors import unprocessable
from app.identity import require_user_id
from app.repo import sleep
from app.schemas import SleepDayOut, SleepRangeOut, SleepSetIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["sleep"])

_MAX_RANGE_DAYS = 400


def _parse_date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise unprocessable(
            "Tarih YYYY-AA-GG biçiminde olmalı", {"field": field}
        ) from None


@router.get("/sleep", response_model=SleepDayOut)
async def get_sleep(
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
) -> SleepDayOut:
    """Bir gecenin uyku süresi.

    Kayıt yoksa `minutes: null` döner, 0 DEĞİL. Ayrım önemli: sıfır "hiç
    uyumadım", null "girmedim" demek ve ortalama hesabında farklı davranmaları
    gerekiyor.
    """
    user_id = require_user_id(x_user_id)
    target = _parse_date(day, "date")

    async with db.pool.acquire() as conn:
        row = await sleep.fetch_day(conn, user_id, target)

    return SleepDayOut(
        date=target.isoformat(),
        minutes=row.minutes if row else None,
    )


@router.put("/sleep", response_model=SleepDayOut)
async def set_sleep(
    payload: SleepSetIn,
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
) -> SleepDayOut:
    """Gecenin süresini ayarlar. Idempotent."""
    user_id = require_user_id(x_user_id)
    target = _parse_date(day, "date")

    async with db.pool.acquire() as conn:
        row = await sleep.set_minutes(conn, user_id, target, payload.minutes)

    logger.info("uyku kaydedildi user_id=%s gün=%s dakika=%d",
                user_id, target, row.minutes)
    return SleepDayOut(date=row.log_date.isoformat(), minutes=row.minutes)


@router.delete("/sleep", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sleep(
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
) -> Response:
    """Kaydı tamamen kaldırır — yanlış girilen geceyi geri almanın yolu.

    Olmayan bir kaydı silmek HATA DEĞİL: sonuç istenen durumla aynı
    (kayıt yok), yani uç idempotent.
    """
    user_id = require_user_id(x_user_id)
    target = _parse_date(day, "date")

    async with db.pool.acquire() as conn:
        await sleep.delete_day(conn, user_id, target)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sleep/range", response_model=SleepRangeOut)
async def get_sleep_range(
    x_user_id: str | None = Header(default=None),
    start_day: str = Query(alias="from"),
    end_day: str = Query(alias="to"),
) -> SleepRangeOut:
    """Aralıktaki gecelerin uyku süreleri."""
    user_id = require_user_id(x_user_id)
    first = _parse_date(start_day, "from")
    last = _parse_date(end_day, "to")

    if last < first:
        raise unprocessable("Bitiş tarihi başlangıçtan önce olamaz")
    if (last - first).days + 1 > _MAX_RANGE_DAYS:
        raise unprocessable("Aralık çok geniş", {"max_days": _MAX_RANGE_DAYS})

    async with db.pool.acquire() as conn:
        rows = await sleep.fetch_range(conn, user_id, first, last)

    return SleepRangeOut(
        days=[
            SleepDayOut(date=row.log_date.isoformat(), minutes=row.minutes)
            for row in rows
        ]
    )
