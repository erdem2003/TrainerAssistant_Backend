"""30 günlük meydan okumalar — katalog ve gün hedefleri (saf mantık).

Sosyal servisteki arkadaş meydan okumalarından AYRI: bu tek kişilik, hazır bir
program ("30 günde 100 şınav"). Saklanan tek şey başlangıç günü
(`repo/challenges.py`); günlük ilerleme o günün antrenmanlarından türetilir
(ADR 0012'nin çizgisi — tamamlanma saklanmaz).

Hedef: dinlenme dışı günlerde başlangıçtan bitişe doğrusal artış, 5'e yuvarlı.
Her 7. gün dinlenme (hedef 0): kas toparlanması + kaçırılan bir günü telafi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

DAYS = 30
REST_EVERY = 7


@dataclass(frozen=True)
class Challenge:
    id: str
    exercise_id: str
    start_target: int
    final_target: int

    def targets(self) -> list[int]:
        work_days = [i for i in range(DAYS) if not _is_rest(i)]
        span = len(work_days) - 1
        result = [0] * DAYS
        for n, i in enumerate(work_days):
            raw = self.start_target + (self.final_target - self.start_target) * n / span
            result[i] = max(5, int(round(raw / 5.0)) * 5)
        return result


def _is_rest(index: int) -> bool:
    return (index + 1) % REST_EVERY == 0


CATALOG: tuple[Challenge, ...] = (
    Challenge("pushup_100", "push_up", 10, 100),
    Challenge("squat_30", "squat", 15, 100),
    Challenge("situp_30", "sit_up", 10, 80),
)
_BY_ID = {c.id: c for c in CATALOG}


def get(challenge_id: str) -> Challenge | None:
    return _BY_ID.get(challenge_id)


@dataclass(frozen=True)
class DayStatus:
    date: date
    target: int
    done: int
    status: str  # REST · DONE · MISSED · TODAY · UPCOMING


def day_statuses(challenge: Challenge, started_on: date, today: date, reps_by_day: dict[date, int]) -> list[DayStatus]:
    days = []
    for i, target in enumerate(challenge.targets()):
        day = started_on + timedelta(days=i)
        done = reps_by_day.get(day, 0)
        if target == 0:
            status = "REST"
        elif done >= target:
            status = "DONE"
        elif day < today:
            status = "MISSED"
        elif day == today:
            status = "TODAY"
        else:
            status = "UPCOMING"
        days.append(DayStatus(date=day, target=target, done=done, status=status))
    return days


def end_date(started_on: date) -> date:
    return started_on + timedelta(days=DAYS - 1)
