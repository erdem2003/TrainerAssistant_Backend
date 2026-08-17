"""GET /v1/analytics/daily — okuma modelinden gunluk toplamlar.

★ BU UC HENUZ GATEWAY'DE YAYINLANMIYOR ★
Mobil uygulama gunluk toplamlari hala `workout-service`'in `/v1/stats/daily`
ucundan aliyor. Ikisini birden yayinlamak, ayni sayi icin IKI kaynak demekti ve
biri digerinden saparsa hangisinin dogru oldugu belirsizlesirdi.

Bu ucun bugunku isi DOGRULAMA: replay'den sonra `workout-service`'in urettigi
sayilarla ayni sonucu verip vermedigini olcmek. Ayni ciktiyi verdigi
dogrulandiginda gateway'in `proxy_pass` hedefi degistirilerek gecis yapilacak —
istemci tarafinda hicbir sey degismeyecek.

Eksik olan tek sey: `form_errors` kirilimi burada JSONB olarak duruyor ama
gunluk toplamda henuz acilmiyor. Gecis oncesi eklenecek.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel

from app.db import db
from app.errors import unprocessable
from app.identity import require_user_id
from app.localday import check_offset, parse_date, range_bounds
from app.repo import facts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["analytics"])

_MAX_RANGE_DAYS = 400


class ExerciseDayOut(BaseModel):
    exercise_id: str
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float


class DayStatsOut(BaseModel):
    date: str
    workouts: int
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float
    by_exercise: list[ExerciseDayOut]


class DailyStatsOut(BaseModel):
    days: list[DayStatsOut]


@router.get("/analytics/daily", response_model=DailyStatsOut)
async def get_daily(
    x_user_id: str | None = Header(default=None),
    start_day: str = Query(alias="from"),
    end_day: str = Query(alias="to"),
    tz_offset: int = Query(default=0),
) -> DailyStatsOut:
    """`workout-service`'in `/v1/stats/daily` ucuyla AYNI biçim."""
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
        rows = await facts.fetch_daily(conn, user_id, offset, start, end)

    by_day: dict[str, list] = {}
    workouts_by_day: dict[str, int] = {}
    for row in rows:
        key = row.local_date.isoformat()
        by_day.setdefault(key, []).append(
            ExerciseDayOut(
                exercise_id=row.exercise_id,
                sets=row.sets,
                reps=row.reps,
                reps_with_errors=row.reps_with_errors,
                active_seconds=row.active_seconds,
            )
        )
        workouts_by_day[key] = workouts_by_day.get(key, 0) + row.workouts

    return DailyStatsOut(
        days=[
            DayStatsOut(
                date=day,
                workouts=workouts_by_day[day],
                sets=sum(i.sets for i in items),
                reps=sum(i.reps for i in items),
                reps_with_errors=sum(i.reps_with_errors for i in items),
                active_seconds=sum(i.active_seconds for i in items),
                by_exercise=items,
            )
            for day, items in sorted(by_day.items())
        ]
    )
