"""Form puanı (0-100) — antrenmanın tekrarlarından.

★ MOBİLDEKİ KOPYAYLA BİREBİR ★ `core/workout/FormScore.kt` aynı formülü
kullanıyor: özet ekranı puanı yükleme beklemeden (ve misafir modunda sunucusuz)
gösteriyor. Formül değişirse İKİ taraf birden değişir (pose-math parity'sinin
aynı gerekçesi).

  tekrar puanı = max(0, 100 − 35 · hata türü sayısı) · min(1, rom / 0.85)
  antrenman puanı = tekrar puanlarının ortalaması, tam sayıya yuvarlı

Kişisel rekor yalnız en az MIN_REPS_FOR_RECORD tekrarlık antrenmanda sayılır:
tek şanslı tekrar 100 puanla rekoru anlamsızlaştırmasın.
"""

from __future__ import annotations

import math

ERROR_PENALTY = 35
FULL_ROM = 0.85
MIN_REPS_FOR_RECORD = 5


def rep_score(error_count: int, rom: float) -> float:
    return max(0.0, 100.0 - ERROR_PENALTY * error_count) * min(1.0, rom / FULL_ROM)


def workout_score(reps: list[tuple[int, float]]) -> int | None:
    """`reps`: (hata türü sayısı, rom) çiftleri. Tekrar yoksa `None`."""
    if not reps:
        return None
    # Yarım yukarı yuvarlama (Kotlin `roundToInt` ile aynı; Python `round` bankacı yuvarlaması).
    return int(math.floor(sum(rep_score(e, rom) for e, rom in reps) / len(reps) + 0.5))
