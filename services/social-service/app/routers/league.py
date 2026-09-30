"""GET /v1/social/league — herkese açık haftalık lig (kurallar `app/league.py`).

İlk çağrıda izleyici bu haftanın bir grubuna yerleşir. Sıra ve puan saklanmaz;
grubun snapshot'larından hesaplanır. Sosyal profili (kullanıcı adı) olmayan
lige giremez: tabloda adıyla görünür.
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel

from app import league
from app.errors import unprocessable
from app.identity import require_user_id
from app.repo import league as league_repo
from app.repo import profiles

router = APIRouter(prefix="/v1/social/league", tags=["league"])


class LeagueEntryOut(BaseModel):
    rank: int
    user_id: str
    username: str | None
    display_name: str
    avatar_seed: str
    is_me: bool
    score: int
    zone: str  # PROMOTE · DEMOTE · STAY


class LeagueResultOut(BaseModel):
    week: str
    shielded: bool = False
    tier_before: str
    tier_after: str
    rank: int
    group_size: int
    score: int


class LeagueOut(BaseModel):
    week_start: str
    ends_at: int  # epoch ms
    tier: str
    tiers: list[str]
    promote_count: int
    demote_count: int
    items: list[LeagueEntryOut]
    last_result: LeagueResultOut | None
    # Bu hafta düşme kalkanı var mı (ödüllü reklam).
    shielded: bool = False


@router.get("", response_model=LeagueOut)
async def my_league(x_user_id: str | None = Header(default=None)) -> LeagueOut:
    viewer_id = require_user_id(x_user_id)
    me = await profiles.find_by_user_id(viewer_id)
    if me is None or not me.social_enabled:
        raise unprocessable("Lige katılmak için önce kullanıcı adı al")

    week = league.week_of(league.utc_now())
    membership = await league_repo.ensure_member(viewer_id, week)
    _, standings = await league_repo.group_standings(membership.group_id)
    by_id = await profiles.profiles_map(s.breakdown.user_id for s in standings)

    items = []
    size = len(standings)
    for s in standings:
        profile = by_id.get(s.breakdown.user_id)
        if profile is None:
            continue  # hesabı silinmiş üye
        items.append(LeagueEntryOut(
            rank=s.rank,
            user_id=str(s.breakdown.user_id),
            username=profile.username,
            display_name=profile.display_name,
            avatar_seed=profile.avatar_seed,
            is_me=s.breakdown.user_id == viewer_id,
            score=s.breakdown.score,
            zone=league.zone(membership.tier, s.rank, size),
        ))

    return LeagueOut(
        week_start=week.isoformat(),
        ends_at=int(league.week_end_utc(week).timestamp() * 1000),
        tier=membership.tier,
        tiers=list(league.TIERS),
        promote_count=league.PROMOTE_COUNT,
        demote_count=league.DEMOTE_COUNT if size >= league.MIN_GROUP_FOR_DEMOTE else 0,
        items=items,
        last_result=LeagueResultOut(**membership.last_result) if membership.last_result else None,
        shielded=await league_repo.is_shielded(viewer_id, week),
    )
