"""Egzersiz kataloğu (ADR 0005: ayrı servis değil).

★ FIRESTORE'DA DEĞİL, KODDA ★ Postgres'te `exercises` tablosu yalnızca
migration'larla (001/002/004/005) doldurulan statik bir listeydi; uygulama hiç
yazmıyordu. Firestore'a taşımak her antrenman yazımına ve her katalog isteğine
bir okuma eklerdi (kota) ve karşılığında hiçbir şey kazandırmazdı. Yeni egzersiz
eklemek yine "spec yaz + buraya bir satır" — migration dosyası yerine bu liste.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Exercise:
    id: str
    display_name: str
    required_view: str


# migrations/001, 002, 004, 005'teki INSERT'lerin birebir aynısı.
_CATALOG: tuple[Exercise, ...] = (
    Exercise("push_up", "Şınav", "SIDE"),
    Exercise("sit_up", "Mekik", "SIDE"),
    Exercise("squat", "Squat", "SIDE"),
    Exercise("bench_press", "Bench Press", "SIDE"),
    Exercise("deadlift", "Deadlift", "SIDE"),
)

_IDS = frozenset(e.id for e in _CATALOG)


def list_all() -> list[Exercise]:
    # `ORDER BY display_name` — kod noktası sırası (Postgres "C" harmanlamasıyla aynı).
    return sorted(_CATALOG, key=lambda e: e.display_name)


def exists(exercise_id: str) -> bool:
    return exercise_id in _IDS
