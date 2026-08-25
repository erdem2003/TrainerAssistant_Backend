"""Rozet kataloğu ve kazanım hesabı (A2). Saf mantık, DB erişimi yok.

Kataloğun kendisi burada koddur, ayrı bir tablo değil: 9 sabit rozet, hiçbiri
kullanıcı tarafından oluşturulmuyor. Yeni bir rozet eklemek bir veri değil, bir
kod değişikliği — `feature-spec` felsefesiyle aynı: sabit kalan şey veri değil,
davranıştır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from app.repo.facts import BadgeStats


def current_streak(active_dates: list[date], today: date) -> int:
    """Mobil `ProgressStats.currentStreak` ile AYNI kural.

    Bugün henüz antrenman yapılmadıysa seri kırılmaz — dün yapıldıysa devam
    ediyor sayılır. İki taraf (Kotlin + Python) aynı sonucu vermeli; burası
    yalnızca rozet ekranı için, istatistik ekranının seri sayısı zaten mobilde
    hesaplanıyor.
    """
    days = set(active_dates)
    if not days:
        return 0
    cursor = today if today in days else today - timedelta(days=1)
    if cursor not in days:
        return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


@dataclass(frozen=True)
class _Ctx:
    stats: BadgeStats
    streak: int


@dataclass(frozen=True)
class BadgeDef:
    id: str
    emoji: str
    label: str
    # 0..1 arası ilerleme oranı üretir; >=1.0 kazanılmış demektir.
    progress: Callable[[_Ctx], float]


_CATALOG: list[BadgeDef] = [
    BadgeDef("streak_7", "🔥", "7 gün", lambda c: c.streak / 7),
    BadgeDef("reps_100", "💯", "100 tekrar", lambda c: c.stats.total_reps / 100),
    BadgeDef("early_bird", "🌅", "Sabah kuşu", lambda c: 1.0 if c.stats.has_early_bird else 0.0),
    BadgeDef("clean_90", "🎯", "%90 temiz", lambda c: (c.stats.best_clean_ratio or 0.0) / 0.90),
    BadgeDef("first_squat", "🏋️", "İlk squat", lambda c: 1.0 if c.stats.has_squat else 0.0),
    BadgeDef("streak_30", "⚡", "30 gün", lambda c: c.streak / 30),
    BadgeDef("reps_500", "🧊", "500 tekrar", lambda c: c.stats.total_reps / 500),
    BadgeDef("night_owl", "🌙", "Gece modu", lambda c: 1.0 if c.stats.has_night_owl else 0.0),
    BadgeDef("clean_95", "👑", "%95 temiz", lambda c: (c.stats.best_clean_ratio or 0.0) / 0.95),
]


@dataclass(frozen=True)
class BadgeResult:
    id: str
    emoji: str
    label: str
    unlocked: bool
    progress: float  # 0..1


def evaluate(stats: BadgeStats, today: date) -> list[BadgeResult]:
    ctx = _Ctx(stats=stats, streak=current_streak(stats.active_local_dates, today))
    results = []
    for b in _CATALOG:
        raw = b.progress(ctx)
        results.append(
            BadgeResult(
                id=b.id, emoji=b.emoji, label=b.label,
                unlocked=raw >= 1.0, progress=max(0.0, min(1.0, raw)),
            )
        )
    return results
