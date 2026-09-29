"""30 günlük meydan okumalar.

GET    /v1/challenges?date=YYYY-MM-DD&tz_offset=N   katalog + katılınanların gün gün durumu
POST   /v1/challenges/{id}/join                      bugünden başlar (yeniden başlatır)
DELETE /v1/challenges/{id}                           bırakır
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Header, Query, status
from pydantic import BaseModel

from app import challenges
from app.errors import not_found
from app.identity import require_user_id
from app.localday import check_offset, parse_date, range_bounds
from app.repo import challenges as joined_repo
from app.repo import workouts

router = APIRouter(prefix="/v1", tags=["challenges"])


class CatalogItemOut(BaseModel):
    id: str
    exercise_id: str
    days: int
    start_target: int
    final_target: int


class DayOut(BaseModel):
    date: str
    target: int
    done: int
    status: str


class ActiveOut(BaseModel):
    id: str
    exercise_id: str
    started_on: str
    day_index: int  # bugün kaçıncı gün (1..30); bittiyse 30'dan büyük
    finished: bool
    completed_days: int
    work_days: int
    days: list[DayOut]


class ChallengesOut(BaseModel):
    catalog: list[CatalogItemOut]
    active: list[ActiveOut]


class JoinIn(BaseModel):
    date: str
    tz_offset: int = 0


async def _reps_by_day(user_id: uuid.UUID, exercise_id: str, first: date, last: date, offset: int) -> dict[date, int]:
    start, end = range_bounds(first, last, offset)
    shift = timedelta(minutes=offset)
    result: dict[date, int] = {}
    for w in await workouts.fetch_between(user_id, start, end):
        if w.exercise_id != exercise_id:
            continue
        day = (w.started_at + shift).date()
        result[day] = result.get(day, 0) + w.total_reps
    return result


async def _build(user_id: uuid.UUID, today: date, offset: int) -> ChallengesOut:
    active = []
    for challenge_id, started_on in sorted((await joined_repo.list_joined(user_id)).items()):
        challenge = challenges.get(challenge_id)
        if challenge is None:
            continue
        last = min(challenges.end_date(started_on), today)
        reps = await _reps_by_day(user_id, challenge.exercise_id, started_on, max(last, started_on), offset)
        days = challenges.day_statuses(challenge, started_on, today, reps)
        work = [d for d in days if d.target > 0]
        active.append(ActiveOut(
            id=challenge.id,
            exercise_id=challenge.exercise_id,
            started_on=started_on.isoformat(),
            day_index=(today - started_on).days + 1,
            finished=today > challenges.end_date(started_on),
            completed_days=sum(1 for d in work if d.status == "DONE"),
            work_days=len(work),
            days=[DayOut(date=d.date.isoformat(), target=d.target, done=d.done, status=d.status) for d in days],
        ))
    catalog = [
        CatalogItemOut(id=c.id, exercise_id=c.exercise_id, days=challenges.DAYS,
                       start_target=c.start_target, final_target=c.final_target)
        for c in challenges.CATALOG
    ]
    return ChallengesOut(catalog=catalog, active=active)


@router.get("/challenges", response_model=ChallengesOut)
async def list_challenges(
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
    tz_offset: int = Query(default=0),
) -> ChallengesOut:
    user_id = require_user_id(x_user_id)
    return await _build(user_id, parse_date(day, "date"), check_offset(tz_offset))


@router.post("/challenges/{challenge_id}/join", response_model=ChallengesOut)
async def join_challenge(challenge_id: str, body: JoinIn, x_user_id: str | None = Header(default=None)) -> ChallengesOut:
    user_id = require_user_id(x_user_id)
    if challenges.get(challenge_id) is None:
        raise not_found("Meydan okuma bulunamadı")
    today = parse_date(body.date, "date")
    offset = check_offset(body.tz_offset)
    await joined_repo.join(user_id, challenge_id, today)
    return await _build(user_id, today, offset)


@router.delete("/challenges/{challenge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def leave_challenge(challenge_id: str, x_user_id: str | None = Header(default=None)) -> None:
    user_id = require_user_id(x_user_id)
    await joined_repo.leave(user_id, challenge_id)
