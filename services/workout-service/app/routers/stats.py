"""GET /v1/stats/daily — Istatistik ekraninin gunluk toplamlari.

Bu ucun mantigi ileride `analytics-service`'e tasinacak (ADR 0006); BICIMI
degismeyecek. Ayrintili gerekce `app/repo/stats.py` basinda.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Header, Query

from app.db import db
from app.errors import unprocessable
from app.identity import require_user_id
from app.localday import check_offset, parse_date, range_bounds
from app.repo import stats
from app.schemas import DailyStatsOut, DayStatsOut, ExerciseDayOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["stats"])

# Istatistik ekraninin en genis gorunumu "Ay" = 30 gun. 400 gun sinir, cunku
# yillik bir gorunum ileride istenebilir ama tum gecmisi tek istekte taramak
# istenmez.
_MAX_RANGE_DAYS = 400


@router.get("/stats/daily", response_model=DailyStatsOut)
async def get_daily_stats(
    x_user_id: str | None = Header(default=None),
    start_day: str = Query(alias="from"),
    end_day: str = Query(alias="to"),
    tz_offset: int = Query(default=0),
) -> DailyStatsOut:
    """Gün gün toplamlar: tekrar, set, aktif süre, egzersiz ve hata kırılımı."""
    user_id = require_user_id(x_user_id)
    first = parse_date(start_day, "from")
    last = parse_date(end_day, "to")
    offset = check_offset(tz_offset)

    if last < first:
        raise unprocessable("Bitiş tarihi başlangıçtan önce olamaz")
    if (last - first).days + 1 > _MAX_RANGE_DAYS:
        raise unprocessable("Aralık çok geniş", {"max_days": _MAX_RANGE_DAYS})

    start, end = range_bounds(first, last, offset)

    async with db.pool.acquire() as conn:
        rows = await stats.fetch_daily(conn, user_id, offset, start, end)
        error_rows = await stats.fetch_daily_errors(conn, user_id, offset, start, end)

    # Gün → egzersiz kırılımı. `rows` gün+egzersiz granülaritesinde geliyor;
    # günün toplamları egzersizler toplanarak çıkıyor. Sunucuda ayrı bir toplam
    # sorgusu daha atmak, aynı sayıyı iki farklı yoldan üretip birbirinden
    # ayrışma riski doğurmak olurdu.
    by_day: dict[date, list[ExerciseDayOut]] = {}
    workouts_by_day: dict[date, int] = {}
    for row in rows:
        by_day.setdefault(row.local_date, []).append(
            ExerciseDayOut(
                exercise_id=row.exercise_id,
                sets=row.sets,
                reps=row.reps,
                reps_with_errors=row.reps_with_errors,
                active_seconds=row.active_seconds,
            )
        )
        workouts_by_day[row.local_date] = row.workouts

    errors_by_day: dict[date, dict[str, int]] = {}
    for row in error_rows:
        errors_by_day.setdefault(row.local_date, {})[row.error] = row.occurrences

    days = [
        DayStatsOut(
            date=day.isoformat(),
            workouts=workouts_by_day.get(day, 0),
            sets=sum(item.sets for item in items),
            reps=sum(item.reps for item in items),
            reps_with_errors=sum(item.reps_with_errors for item in items),
            active_seconds=sum(item.active_seconds for item in items),
            by_exercise=items,
            form_errors=errors_by_day.get(day, {}),
        )
        for day, items in sorted(by_day.items())
    ]

    return DailyStatsOut(days=days)
