"""Günlük görevler + XP/seviye.

GET  /v1/quests?date=YYYY-MM-DD&tz_offset=N   günün 3 görevi, ilerleme, XP ve seviye
POST /v1/quests/claim                         tamamlanan görevin XP'sini toplar

Görevler ve ilerleme saklanmaz, her istekte türetilir (`app/quests.py`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from app import quests
from app.errors import not_found, unprocessable
from app.identity import require_user_id
from app.localday import check_offset, day_bounds, parse_date
from app.repo import progress, workouts

router = APIRouter(prefix="/v1", tags=["quests"])

# Toplama yalnız bugün ve dün için: gece yarısını geçen kullanıcı dünkü ödülünü
# kaçırmasın, ama geçmişe dönük toplu toplama olmasın.
_CLAIM_WINDOW_DAYS = 1


class QuestOut(BaseModel):
    id: str
    kind: str
    target: int
    progress: int
    xp: int
    exercise_id: str | None
    completed: bool
    claimed: bool


class QuestDayOut(BaseModel):
    date: str
    quests: list[QuestOut]
    xp: int
    level: int
    level_start_xp: int
    next_level_xp: int


class ClaimIn(BaseModel):
    date: str
    quest_id: str = Field(min_length=1, max_length=40)
    tz_offset: int = 0


async def _day_totals(user_id: uuid.UUID, day: date, offset: int) -> quests.DayTotals:
    start, end = day_bounds(day, offset)
    totals = quests.DayTotals()
    for w in await workouts.fetch_between(user_id, start, end):
        totals.add(w.exercise_id, w.total_reps, w.reps_with_errors, w.total_sets, w.active_seconds)
    return totals


async def _build(user_id: uuid.UUID, day: date, offset: int) -> QuestDayOut:
    day_quests = quests.quests_for(user_id, day)
    totals = await _day_totals(user_id, day, offset)
    claimed = await progress.claimed_ids(user_id, day, [q.id for q in day_quests])
    state = await progress.get_state(user_id)
    level = quests.level_for(state.total)
    return QuestDayOut(
        date=day.isoformat(),
        quests=[
            QuestOut(
                id=q.id, kind=q.kind, target=q.target, progress=quests.progress(q, totals), xp=q.xp,
                exercise_id=q.exercise_id, completed=quests.progress(q, totals) >= q.target,
                claimed=q.id in claimed,
            )
            for q in day_quests
        ],
        xp=state.total,
        level=level,
        level_start_xp=quests.xp_for_level(level),
        next_level_xp=quests.xp_for_level(level + 1),
    )


def _local_today(offset: int) -> date:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()


@router.get("/quests", response_model=QuestDayOut)
async def get_quests(
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
    tz_offset: int = Query(default=0),
) -> QuestDayOut:
    user_id = require_user_id(x_user_id)
    return await _build(user_id, parse_date(day, "date"), check_offset(tz_offset))


@router.post("/quests/claim", response_model=QuestDayOut)
async def claim_quest(body: ClaimIn, x_user_id: str | None = Header(default=None)) -> QuestDayOut:
    user_id = require_user_id(x_user_id)
    offset = check_offset(body.tz_offset)
    day = parse_date(body.date, "date")
    today = _local_today(offset)
    if not (today - timedelta(days=_CLAIM_WINDOW_DAYS) <= day <= today):
        raise unprocessable("Bu günün görev ödülü toplanamaz", {"date": body.date})

    quest = next((q for q in quests.quests_for(user_id, day) if q.id == body.quest_id), None)
    if quest is None:
        raise not_found("Görev bulunamadı")
    totals = await _day_totals(user_id, day, offset)
    if quests.progress(quest, totals) < quest.target:
        raise unprocessable("Görev henüz tamamlanmadı", {"quest_id": quest.id})
    # Zaten toplanmışsa sessizce aynı durum döner (idempotent).
    await progress.claim(user_id, day, quest.id, quest.xp)
    return await _build(user_id, day, offset)
