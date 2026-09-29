"""GET/PUT /v1/plan — gunluk antrenman programi.

Tamamlanma bu servisin BASKA tablosundan (workouts/sets/reps) turetiliyor;
plan tablosunda "yapildi" diye bir kolon yok. Gerekcesi migrations/003_plan.sql.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from app import adaptive
from app.errors import unprocessable
from app.identity import require_user_id
from app.localday import check_offset, day_bounds, parse_date, range_bounds
from app.repo import exercises, plan, workouts
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

    rows = await plan.fetch_day(user_id, target_day)
    done = await plan.done_reps(user_id, start, end)

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

    # Bilinmeyen egzersiz kataloğa karşı doğrulanıyor; hangi id'nin geçersiz
    # olduğu söyleniyor.
    for item in payload.items:
        if not exercises.exists(item.exercise_id):
            raise unprocessable(
                "Bilinmeyen egzersiz", {"exercise_id": item.exercise_id}
            )

    # Günün tamamı TEK dokümanın tek yazımı — "silindi ama eklenmedi" ara
    # durumu oluşamaz (Postgres'te bunun için transaction gerekiyordu).
    await plan.replace_day(user_id, target_day, payload.items)

    rows = await plan.fetch_day(user_id, target_day)
    done = await plan.done_reps(user_id, start, end)

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

    rows = await plan.fetch_range(user_id, first, last)
    done_by_day = await plan.done_reps_by_day(user_id, offset, start, end)

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


# --- Uyarlanabilir program (öneri) -------------------------------------------

_SUGGESTION_WINDOW_DAYS = 7
# Öneri uygulanınca bugünden itibaren bu kadar günün hedefi değişir (şablonla
# ileriye yazılmış günler dahil).
_APPLY_DAYS = 14


class SuggestionOut(BaseModel):
    exercise_id: str
    current_target: int
    suggested_target: int
    direction: str
    reason: str
    hit_rate: float
    clean_ratio: float | None
    planned_days: int


class SuggestionsOut(BaseModel):
    items: list[SuggestionOut]


class ApplySuggestionIn(BaseModel):
    date: str
    exercise_id: str
    target_reps: int = Field(ge=1, le=10_000)


@router.get("/plan/suggestions", response_model=SuggestionsOut)
async def get_suggestions(
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
    tz_offset: int = Query(default=0),
) -> SuggestionsOut:
    """Son 7 günün program sonucuna göre hedef önerileri (`app/adaptive.py`)."""
    user_id = require_user_id(x_user_id)
    today = parse_date(day, "date")
    offset = check_offset(tz_offset)
    first = today - timedelta(days=_SUGGESTION_WINDOW_DAYS)
    last = today - timedelta(days=1)
    start, end = range_bounds(first, last, offset)

    rows = await plan.fetch_range(user_id, first, last)
    shift = timedelta(minutes=offset)
    done: dict[tuple[date, str], int] = {}
    reps: dict[str, int] = {}
    clean: dict[str, int] = {}
    for w in await workouts.fetch_between(user_id, start, end):
        key = ((w.started_at + shift).date(), w.exercise_id)
        done[key] = done.get(key, 0) + w.total_reps
        reps[w.exercise_id] = reps.get(w.exercise_id, 0) + w.total_reps
        clean[w.exercise_id] = clean.get(w.exercise_id, 0) + max(0, w.total_reps - w.reps_with_errors)

    # Güncel hedef: bugünün programı, yoksa son planlandığı gün.
    today_targets = {r.exercise_id: r.target_reps for r in await plan.fetch_day(user_id, today)}
    planned: dict[str, list] = {}
    for row in rows:
        planned.setdefault(row.exercise_id, []).append(row)

    items = []
    for exercise_id, ex_rows in sorted(planned.items()):
        latest = max(ex_rows, key=lambda r: r.scheduled_date)
        week = adaptive.ExerciseWeek(
            exercise_id=exercise_id,
            current_target=today_targets.get(exercise_id, latest.target_reps),
            planned_days=len(ex_rows),
            hit_days=sum(1 for r in ex_rows if done.get((r.scheduled_date, exercise_id), 0) >= r.target_reps),
            reps=reps.get(exercise_id, 0),
            clean_reps=clean.get(exercise_id, 0),
        )
        suggestion = adaptive.suggest(week)
        if suggestion is not None:
            items.append(SuggestionOut(**suggestion.__dict__))
    return SuggestionsOut(items=items)


@router.post("/plan/suggestions/apply", response_model=PlanDayOut)
async def apply_suggestion(body: ApplySuggestionIn, x_user_id: str | None = Header(default=None)) -> PlanDayOut:
    """Öneriyi bugünden itibaren programdaki günlere uygular; bugünün programını döner."""
    user_id = require_user_id(x_user_id)
    today = parse_date(body.date, "date")
    if not exercises.exists(body.exercise_id):
        raise unprocessable("Bilinmeyen egzersiz", {"exercise_id": body.exercise_id})
    changed = await plan.set_target_range(
        user_id, body.exercise_id, body.target_reps, today, today + timedelta(days=_APPLY_DAYS - 1),
    )
    logger.info("program önerisi uygulandı exercise=%s target=%d gün=%d", body.exercise_id, body.target_reps, changed)
    rows = await plan.fetch_day(user_id, today)
    items = _to_items(rows, {})
    return PlanDayOut(date=today.isoformat(), items=items, completed=False)
