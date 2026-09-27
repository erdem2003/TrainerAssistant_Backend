"""GET /v1/social/leaderboards/weekly (ADR 0014, Faz S5).

Hiçbir şey saklanmıyor (ADR 0012) — bu uç izleyici + arkadaşlarının o haftaki
snapshot'larından sorgu anında hesaplar. Formül `app/scoring.py`'de, hafta
sınırı `app/localday.py`'de. Okuma: haftadaki snapshot sayısı + profiller.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Header, Query

from app import localday, scoring
from app.identity import require_user_id
from app.repo import friendships, profiles, snapshots
from app.schemas import LeaderboardEntryOut, LeaderboardOut

router = APIRouter(prefix="/v1/social/leaderboards", tags=["leaderboards"])


@router.get("/weekly", response_model=LeaderboardOut)
async def weekly_leaderboard(
    week_start: str = Query(),
    tz_offset: int = Query(),
    x_user_id: str | None = Header(default=None),
) -> LeaderboardOut:
    viewer_id = require_user_id(x_user_id)
    start_day = localday.parse_date(week_start, "week_start")
    offset = localday.check_offset(tz_offset)
    end_day = start_day + timedelta(days=6)
    start_utc, end_utc = localday.range_bounds(start_day, end_day, offset)

    friend_rows = await friendships.list_friends(viewer_id)
    author_ids = [viewer_id, *(row["friend_id"] for row in friend_rows)]

    stats_rows = await snapshots.fetch_weekly_stats(author_ids, start_utc, end_utc, offset)
    stats_by_user = {row["user_id"]: row for row in stats_rows}

    breakdowns = []
    for author_id in author_ids:
        row = stats_by_user.get(author_id)
        breakdowns.append(
            scoring.compute(
                author_id,
                total_reps=row["total_reps"] if row else 0,
                clean_reps=row["clean_reps"] if row else 0,
                total_sets=row["total_sets"] if row else 0,
                active_days=row["active_days"] if row else 0,
            )
        )

    # ★ DETERMİNİSTİK SIRALAMA ★ Eşit skorda kimin önce göründüğü her sorguda
    # AYNI olmalı — üçüncü kırıcı olarak user_id (rastgele değil, kararlı).
    breakdowns.sort(key=lambda b: (-b.score, -b.clean_reps, str(b.user_id)))

    by_id = await profiles.profiles_map(b.user_id for b in breakdowns)

    items = []
    for rank, b in enumerate(breakdowns, start=1):
        profile = by_id.get(b.user_id)
        if profile is None:
            # Profil silinmiş (fanout henüz işlenmemiş olabilir) — atla.
            continue
        items.append(
            LeaderboardEntryOut(
                rank=rank,
                user_id=str(b.user_id),
                username=profile.username,
                display_name=profile.display_name,
                avatar_seed=profile.avatar_seed,
                is_me=(b.user_id == viewer_id),
                score=b.score,
                total_reps=b.total_reps,
                clean_reps=b.clean_reps,
                total_sets=b.total_sets,
                active_days=b.active_days,
                rep_points=b.rep_points,
                clean_bonus_points=b.clean_bonus_points,
                consistency_points=b.consistency_points,
            )
        )

    return LeaderboardOut(week_start=week_start, items=items)
