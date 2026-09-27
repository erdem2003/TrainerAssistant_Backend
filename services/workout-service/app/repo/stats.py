"""Günlük toplamlar — İstatistik ekranının tek veri kaynağı.

★ NEDEN BU UÇ VAR ★
İstatistik ekranı gün bazında kalori, tekrar, set ve form hatası dağılımı
gösteriyor. Bunları geçmiş listesinden türetmek MÜMKÜN değildi: liste yanıtı
tekrarları ve hataları taşımıyor, ayrıntıya inmek için antrenman başına bir
istek gerekirdi.

★ FIRESTORE KARŞILIĞI ★
Postgres'teki CTE'ler (set_agg / rep_agg / workout_count / hata dağılımı) artık
tek bir aralık sorgusunun üzerinde bellek içi toplama. Kartezyen tuzağı
(set × tekrar × hata JOIN'inde `active_seconds`'ın şişmesi) burada tanım gereği
yok: her antrenman dokümanı toplamlarını yazım anında hesaplanmış olarak taşıyor
(`repo/workouts.build_document`). Okuma maliyeti: aralıktaki antrenman başına
1 doküman; setler/tekrarlar `select()` ile çekilmiyor.

★ KALORİ BURADA HESAPLANMIYOR ★ (ADR 0010) — yalnızca `active_seconds` döner.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.repo import workouts


@dataclass(frozen=True)
class ExerciseDayRow:
    local_date: date
    exercise_id: str
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float
    workouts: int


@dataclass(frozen=True)
class ErrorDayRow:
    local_date: date
    error: str
    occurrences: int


async def fetch_daily(
    user_id: uuid.UUID,
    offset_minutes: int,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[list[ExerciseDayRow], list[ErrorDayRow]]:
    """Gün × egzersiz toplamları VE gün × form hatası dağılımı — tek sorgudan.

    Postgres'te iki ayrı sorguydu; burada ikisini ayrı çekmek aynı dokümanları
    iki kez okumak (iki kat kota) olurdu.
    """
    offset = timedelta(minutes=offset_minutes)
    per_ex: dict[tuple[date, str], dict] = {}
    workouts_per_day: dict[date, int] = {}
    errors: dict[tuple[date, str], int] = {}

    for w in await workouts.fetch_between(user_id, start_utc, end_utc):
        day = (w.started_at + offset).date()
        workouts_per_day[day] = workouts_per_day.get(day, 0) + 1
        agg = per_ex.setdefault((day, w.exercise_id), {"sets": 0, "reps": 0, "rwe": 0, "active": 0.0})
        agg["sets"] += w.total_sets
        agg["reps"] += w.total_reps
        agg["rwe"] += w.reps_with_errors
        agg["active"] += w.active_seconds
        for error, count in w.form_errors.items():
            errors[(day, error)] = errors.get((day, error), 0) + int(count)

    rows = [
        ExerciseDayRow(
            local_date=day,
            exercise_id=exercise_id,
            sets=agg["sets"],
            reps=agg["reps"],
            reps_with_errors=agg["rwe"],
            active_seconds=float(agg["active"]),
            workouts=workouts_per_day[day],
        )
        for (day, exercise_id), agg in sorted(per_ex.items())
    ]
    error_rows = [
        ErrorDayRow(local_date=day, error=error, occurrences=count)
        for (day, error), count in sorted(errors.items())
    ]
    return rows, error_rows
