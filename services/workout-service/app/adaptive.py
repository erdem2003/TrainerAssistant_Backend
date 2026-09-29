"""Uyarlanabilir program — son 7 günün sonuçlarından hedef önerisi (saf mantık).

Öneri OTOMATİK UYGULANMAZ: kullanıcı "Uygula" der (hedef onun). Kurallar
egzersiz başına, son 7 günde programda en az MIN_PLANNED_DAYS gün olan
egzersizler için:

  - hedefi tutturma ≥ %80 VE temiz oran ≥ %80  → hedef %15 artar (en az +5)
  - hedefi tutturma ≤ %40                       → hedef %15 azalır
  - temiz oran < %60 (tutturma yeterli olsa da)  → hedef %15 azalır: sayı
    yerine forma odaklan (sakatlık riski — ürünün asıl vaadi form)
  - aksi hâlde öneri yok

Hedefler 5'in katına yuvarlanır, en az 5.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_PLANNED_DAYS = 3
STEP = 0.15


@dataclass(frozen=True)
class ExerciseWeek:
    exercise_id: str
    current_target: int
    planned_days: int
    hit_days: int
    reps: int
    clean_reps: int

    @property
    def hit_rate(self) -> float:
        return self.hit_days / self.planned_days if self.planned_days else 0.0

    @property
    def clean_ratio(self) -> float | None:
        return self.clean_reps / self.reps if self.reps else None


@dataclass(frozen=True)
class Suggestion:
    exercise_id: str
    current_target: int
    suggested_target: int
    direction: str  # UP · DOWN
    reason: str  # CONSISTENT · MISSED · FORM
    hit_rate: float
    clean_ratio: float | None
    planned_days: int


def _round5(value: float) -> int:
    return max(5, int(round(value / 5.0)) * 5)


def suggest(week: ExerciseWeek) -> Suggestion | None:
    if week.planned_days < MIN_PLANNED_DAYS or week.current_target <= 0:
        return None
    clean = week.clean_ratio
    target = week.current_target
    if clean is not None and clean < 0.6 and week.hit_rate > 0.4:
        new, direction, reason = _round5(target * (1 - STEP)), "DOWN", "FORM"
    elif week.hit_rate <= 0.4:
        new, direction, reason = _round5(target * (1 - STEP)), "DOWN", "MISSED"
    elif week.hit_rate >= 0.8 and clean is not None and clean >= 0.8:
        new, direction, reason = max(target + 5, _round5(target * (1 + STEP))), "UP", "CONSISTENT"
    else:
        return None
    if new == target:
        return None
    return Suggestion(
        exercise_id=week.exercise_id, current_target=target, suggested_target=new,
        direction=direction, reason=reason, hit_rate=round(week.hit_rate, 2),
        clean_ratio=round(clean, 2) if clean is not None else None, planned_days=week.planned_days,
    )
