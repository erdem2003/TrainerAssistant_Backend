"""Günlük görevler ve seviye — saf mantık (Firestore'a dokunmaz).

★ GÖREVLER SAKLANMAZ ★ (ADR 0012'nin çizgisi) Günün üç görevi kullanıcı + tarih
özetinden DETERMİNİSTİK üretiliyor; ilerleme o günün antrenmanlarından
hesaplanıyor. Saklanan tek şey "ödül toplandı" kaydı (`repo/progress.py`) —
aynı görevin XP'si iki kez verilmesin diye.

Metin sunucuda üretilmiyor: istemci `kind` + `target` + `exercise_id`'den kendi
dilinde yazıyor (TR birincil, EN ikincil).

XP:
  - her tekrar 1, formu temiz her tekrar +1 (yazımda eklenir, `rep_xp`)
  - toplanan görev ödülleri (`quest_xp`)
Seviye L'ye ulaşmak için gereken XP: 50·L·(L−1) → 2: 100, 3: 300, 4: 600, 5: 1000.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import date

QUESTS_PER_DAY = 3

# Görev türü → (hedef seçenekleri, hedef başına XP). Hedef seçimi zorlukla
# XP'yi birlikte büyütür.
_POOL: dict[str, tuple[tuple[int, int], ...]] = {
    "REPS": ((30, 30), (50, 40), (80, 60)),
    "CLEAN_REPS": ((20, 40), (30, 50), (40, 70)),
    "SETS": ((2, 30), (3, 40), (4, 50)),
    "EXERCISE_REPS": ((15, 40), (20, 45), (25, 50)),
    "ACTIVE_SECONDS": ((180, 30), (300, 45)),
}
# Egzersiz görevi yalnız ekipmansız egzersizlerden: bench/deadlift herkeste yok.
_QUEST_EXERCISES = ("push_up", "squat", "sit_up")


@dataclass(frozen=True)
class Quest:
    id: str
    kind: str
    target: int
    xp: int
    exercise_id: str | None = None


@dataclass
class DayTotals:
    reps: int = 0
    clean_reps: int = 0
    sets: int = 0
    active_seconds: float = 0.0
    reps_by_exercise: dict[str, int] = field(default_factory=dict)

    def add(self, exercise_id: str, total_reps: int, reps_with_errors: int, total_sets: int, active_seconds: float) -> None:
        self.reps += total_reps
        self.clean_reps += max(0, total_reps - reps_with_errors)
        self.sets += total_sets
        self.active_seconds += active_seconds
        self.reps_by_exercise[exercise_id] = self.reps_by_exercise.get(exercise_id, 0) + total_reps


def rep_xp(total_reps: int, reps_with_errors: int) -> int:
    return total_reps + max(0, total_reps - reps_with_errors)


def quests_for(user_id: uuid.UUID, day: date, extra: bool = False) -> list[Quest]:
    """`extra` (ödüllü reklam): 4. görev. İlk üç görev `extra`dan BAĞIMSIZ aynı —
    türler tam permütasyondan sırayla alınıyor, hedefler de aynı sırayla çekiliyor."""
    seed = hashlib.sha256(f"{user_id}|{day.isoformat()}".encode()).digest()
    rng = random.Random(seed)
    kinds = rng.sample(sorted(_POOL), len(_POOL))[: QUESTS_PER_DAY + (1 if extra else 0)]
    quests = []
    for kind in kinds:
        target, xp = rng.choice(_POOL[kind])
        exercise_id = rng.choice(_QUEST_EXERCISES) if kind == "EXERCISE_REPS" else None
        quests.append(Quest(id=kind.lower(), kind=kind, target=target, xp=xp, exercise_id=exercise_id))
    return quests


def progress(quest: Quest, totals: DayTotals) -> int:
    value = {
        "REPS": totals.reps,
        "CLEAN_REPS": totals.clean_reps,
        "SETS": totals.sets,
        "EXERCISE_REPS": totals.reps_by_exercise.get(quest.exercise_id or "", 0),
        "ACTIVE_SECONDS": int(totals.active_seconds),
    }[quest.kind]
    return min(value, quest.target)


def xp_for_level(level: int) -> int:
    return 50 * level * (level - 1)


def level_for(xp: int) -> int:
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level
