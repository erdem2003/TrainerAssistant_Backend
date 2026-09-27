"""Haftalık skor formülü (ADR 0014, Faz S5).

★ FORMÜL BURADA, TEK YERDE ★ Mobil taraf kendi hesaplamaz — dönen bileşenler
zaten toplama eşit olduğu için istemci istese de yanlış toplayamaz, yalnızca
gösterir. Formül değişirse tek dosya değişir.

v1 ağırlıkları bilinçli basit tutuldu:
  - her tekrar 1 puan
  - HATASIZ her tekrar +1 EK puan (temiz tekrar, hatalı tekrardan 2 kat değerli)
  - haftanın her AYRI aktif günü +15 puan (tek büyük seansı değil, haftaya
    yayılmış tutarlılığı ödüllendirir)

Global "streak" (art arda gün) BİLEREK skor formülüne dahil değil: haftalık
pencere zaten kendi içinde tutarlılığı (`active_days`) ölçüyor; günler arası
zincir kavramı hafta sınırında kesilince ("pazar gecesi başlayan zincir
pazartesi sıfırlanır mı") tutarsız bir sinyal üretir — ADR 0014'ün konusu değil,
ileride ayrı bir "genel seri" özelliği olarak ele alınabilir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

REP_POINTS = 1
CLEAN_REP_BONUS = 1
ACTIVE_DAY_POINTS = 15


@dataclass(frozen=True)
class ScoreBreakdown:
    user_id: uuid.UUID
    total_reps: int
    clean_reps: int
    total_sets: int
    active_days: int
    rep_points: int
    clean_bonus_points: int
    consistency_points: int
    score: int


def compute(
    user_id: uuid.UUID,
    *,
    total_reps: int,
    clean_reps: int,
    total_sets: int,
    active_days: int,
) -> ScoreBreakdown:
    rep_points = total_reps * REP_POINTS
    clean_bonus_points = clean_reps * CLEAN_REP_BONUS
    consistency_points = active_days * ACTIVE_DAY_POINTS
    return ScoreBreakdown(
        user_id=user_id,
        total_reps=total_reps,
        clean_reps=clean_reps,
        total_sets=total_sets,
        active_days=active_days,
        rep_points=rep_points,
        clean_bonus_points=clean_bonus_points,
        consistency_points=consistency_points,
        score=rep_points + clean_bonus_points + consistency_points,
    )
