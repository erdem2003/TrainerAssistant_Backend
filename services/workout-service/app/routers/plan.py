"""GET/PUT /v1/plan — gunluk antrenman programi.

Tamamlanma bu servisin BASKA tablosundan (workouts/sets/reps) turetiliyor;
plan tablosunda "yapildi" diye bir kolon yok. Gerekcesi migrations/003_plan.sql.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Header, Query

from app.db import db
from app.errors import unprocessable
from app.identity import require_user_id
from app.localday import check_offset, day_bounds, parse_date, range_bounds
from app.repo import exercises, plan
from app.schemas import (
    PlanDayIn,
    PlanDayOut,
    PlanDaySummary,
    PlanItemOut,
    PlanRangeOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["plan"])

# Aralik ucunun ust siniri. Gun seridi 14 gun gosteriyor; 92 gun (bir ceyrek)
# fazlasiyla pay birakiyor ve tek istekle butun gecmisi taramayi engelliyor.
_MAX_RANGE_DAYS = 92


def _to_items(rows: list, done: dict[str, int]) -> list[PlanItemOut]:
    return [
        PlanItemOut(
            id=str(row.id),
            exercise_id=row.exercise_id,
            target_reps=row.target_reps,
            # Hedefin uzerine cikmak MUMKUN ve kirpilmiyor: kullanici 5 hedefiyle
            # 8 tekrar yaptiysa 8 gormeli. Kirpma yalnizca ilerleme cubugunda,
            # istemci tarafinda yapiliyor.
            done_reps=done.get(row.exercise_id, 0),
            scheduled_time=row.scheduled_time,
            completed=done.get(row.exercise_id, 0) >= row.target_reps,
        )
        for row in rows
    ]


@router.get("/plan", response_model=PlanDayOut)
async def get_plan(
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
    tz_offset: int = Query(default=0),
) -> PlanDayOut:
    """Bir günün programı + o gün gerçekleşen tekrarlar."""
    user_id = require_user_id(x_user_id)
    target_day = parse_date(day, "date")
    offset = check_offset(tz_offset)
    start, end = day_bounds(target_day, offset)

    async with db.pool.acquire() as conn:
        rows = await plan.fetch_day(conn, user_id, target_day)
        done = await plan.done_reps(conn, user_id, start, end)

    items = _to_items(rows, done)
    return PlanDayOut(
        date=target_day.isoformat(),
        items=items,
        # Boş program tamamlanmış SAYILMAZ — bkz. PlanDayOut.
        completed=bool(items) and all(item.completed for item in items),
    )


@router.put("/plan", response_model=PlanDayOut)
async def put_plan(
    payload: PlanDayIn,
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
    tz_offset: int = Query(default=0),
) -> PlanDayOut:
    """Günün listesini komple değiştirir (kısmi güncelleme yok)."""
    user_id = require_user_id(x_user_id)
    target_day = parse_date(day, "date")
    offset = check_offset(tz_offset)
    start, end = day_bounds(target_day, offset)

    async with db.pool.acquire() as conn:
        # Bilinmeyen egzersiz veritabanı foreign key'ine takılırdı ama oradan
        # gelen hata 500 olurdu; burada hangi id'nin geçersiz olduğu söyleniyor.
        for item in payload.items:
            if not await exercises.exists(conn, item.exercise_id):
                raise unprocessable(
                    "Bilinmeyen egzersiz", {"exercise_id": item.exercise_id}
                )

        # TEK TRANSACTION: silme başarılı olup ekleme patlarsa kullanıcının
        # programı sessizce silinmiş olurdu.
        async with conn.transaction():
            await plan.replace_day(conn, user_id, target_day, payload.items)

        rows = await plan.fetch_day(conn, user_id, target_day)
        done = await plan.done_reps(conn, user_id, start, end)

    logger.info(
        "program yazıldı user_id=%s gün=%s kalem=%d",
        user_id, target_day, len(payload.items),
    )

    items = _to_items(rows, done)
    return PlanDayOut(
        date=target_day.isoformat(),
        items=items,
        completed=bool(items) and all(item.completed for item in items),
    )


@router.get("/plan/range", response_model=PlanRangeOut)
async def get_plan_range(
    x_user_id: str | None = Header(default=None),
    start_day: str = Query(alias="from"),
    end_day: str = Query(alias="to"),
    tz_offset: int = Query(default=0),
) -> PlanRangeOut:
    """Gün şeridi işaretleri — hangi günde plan var, hangisi tamamlandı.

    Ayrıntı DÖNMÜYOR: şerit 14 gün gösteriyor ve her günün kalemlerini
    göndermek yanıtı gereksiz büyütürdü. Bir güne dokunulduğunda `GET /v1/plan`
    çağrılıyor.
    """
    user_id = require_user_id(x_user_id)
    first = parse_date(start_day, "from")
    last = parse_date(end_day, "to")
    offset = check_offset(tz_offset)

    if last < first:
        raise unprocessable("Bitiş tarihi başlangıçtan önce olamaz")
    if (last - first).days + 1 > _MAX_RANGE_DAYS:
        raise unprocessable(
            "Aralık çok geniş", {"max_days": _MAX_RANGE_DAYS}
        )

    start, end = range_bounds(first, last, offset)

    async with db.pool.acquire() as conn:
        rows = await plan.fetch_range(conn, user_id, first, last)
        done_by_day = await plan.done_reps_by_day(conn, user_id, offset, start, end)

    grouped: dict[date, list] = {}
    for row in rows:
        grouped.setdefault(row.scheduled_date, []).append(row)

    days = []
    for day_key in sorted(grouped):
        done = done_by_day.get(day_key, {})
        items = grouped[day_key]
        completed_count = sum(
            1 for item in items if done.get(item.exercise_id, 0) >= item.target_reps
        )
        days.append(
            PlanDaySummary(
                date=day_key.isoformat(),
                item_count=len(items),
                completed_count=completed_count,
                completed=completed_count == len(items),
            )
        )

    return PlanRangeOut(days=days)
