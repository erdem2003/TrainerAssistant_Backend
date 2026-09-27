"""workout_facts izdüşümü + kullanıcı özeti — olay akışının okuma modeli.

★ OKUMA BÜTÇESİ (Firestore ücretsiz planı: günde 50k okuma) ★
Postgres'teki üç toplama sorgusu burada iki farklı yoldan cevaplanıyor; seçim
"istek başına kaç doküman okunur" sorusuna göre yapıldı:

  /daily, /errors  → ARALIK SORGUSU, bellek içi toplama.
                     Okuma = aralıktaki antrenman sayısı (30 gün ≈ 30-60).
                     Özet dokümanı YOK çünkü gün sınırı isteğin `tz_offset`'ine
                     bağlı: UTC günüyle önceden toplanmış bir kova, UTC+3
                     kullanıcısının gece 01:00 antrenmanını yanlış güne yazardı.
                     Aralık sorgusu tek alanlı (`started_at`) otomatik indeksle
                     çalışıyor; `exercise` filtresi bileşik indeks istemesin
                     diye bellekte uygulanıyor.

  /badges          → TEK DOKÜMAN: `analytics_users/{uid}` özeti.
                     Rozetler kullanıcının TÜM geçmişine bakıyor (toplam tekrar,
                     en temiz set, hiç squat var mı, sabah/gece antrenmanı, seri).
                     Her istekte tüm fact'leri okumak geçmişle doğrusal büyürdü.
                     Özet, fact ile AYNI transaction'da güncelleniyor.

★ ÖZET NASIL `tz_offset`'TEN BAĞIMSIZ KALIYOR ★
Sabah kuşu / gece modu / aktif günler yerel saate bağlı ve saat dilimi isteğin
parametresi. Özet bu yüzden hazır bayrak değil, antrenman başlangıçlarının
dakika çözünürlüklü listesini (`started_minutes`, epoch dakika) tutuyor; yerel
saat/tarih okuma anında HERHANGİ bir farkla birebir hesaplanıyor (yerel saat ve
tarih dakikanın altındaki kısımdan etkilenmez). Büyüme: antrenman başına bir
tamsayı — günde 10 antrenmanla 3 yıl ≈ 11k sayı ≈ 100 KB, 1 MiB sınırının
çok altında.

★ REPLAY ★ Fact yazımı UPSERT (Postgres'teki `ON CONFLICT DO UPDATE`); özet
eski fact'in katkısını çıkarıp yenisini ekleyerek güncelleniyor, yani aynı olayı
replay'de yeniden işlemek toplamı İKİYE KATLAMAZ. Bilinen sınır: aynı
`workout_id` farklı bir başlangıç dakikasıyla yeniden gelirse eski dakika
listeden düşmüyor (antrenmanlar değişmez — içerik değişikliği workout-service'te
409); `rebuild_summary` bunu sıfırdan düzeltir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore

from app.db import db, user_doc

# `best_clean_ratio` en az bu kadar tekrarlık antrenmanları dikkate alır:
# 1 tekrarlık şanslı bir set %100 görünüp rozeti anlamsızlaştırmasın.
_MIN_REPS_FOR_CLEAN_RATIO = 5


@dataclass(frozen=True)
class ErrorCountRow:
    error_name: str
    occurrences: int


@dataclass(frozen=True)
class BadgeStats:
    total_reps: int
    best_clean_ratio: float | None
    has_squat: bool
    has_early_bird: bool
    has_night_owl: bool
    active_local_dates: list[date]


@dataclass(frozen=True)
class ExerciseDayRow:
    local_date: date
    exercise_id: str
    workouts: int
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float


def facts_col(user_id: uuid.UUID | str):
    return user_doc(user_id).collection("facts")


def fact_ref(user_id: uuid.UUID | str, workout_id: uuid.UUID | str):
    return facts_col(user_id).document(str(workout_id))


def build_fact(
    *,
    user_id: uuid.UUID,
    exercise_id: str,
    started_at: datetime,
    ended_at: datetime | None,
    total_sets: int,
    total_reps: int,
    reps_with_errors: int,
    best_set_reps: int,
    total_active_seconds: float,
    form_errors: dict,
) -> dict:
    return {
        "user_id": str(user_id),
        "exercise_id": exercise_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "total_sets": int(total_sets),
        "total_reps": int(total_reps),
        "reps_with_errors": int(reps_with_errors),
        "best_set_reps": int(best_set_reps),
        "total_active_seconds": float(total_active_seconds),
        "form_errors": {str(k): int(v) for k, v in (form_errors or {}).items()},
    }


def _clean_ratio(fact: dict) -> float | None:
    total = int(fact.get("total_reps", 0))
    if total < _MIN_REPS_FOR_CLEAN_RATIO:
        return None
    return (total - int(fact.get("reps_with_errors", 0))) / total


def _epoch_minute(moment: datetime) -> int:
    return int(moment.timestamp()) // 60


def fold_summary(current: dict | None, old_fact: dict | None, new_fact: dict) -> dict:
    """Özeti bir fact'in upsert'üyle günceller (saf fonksiyon).

    Eski fact'in katkısı çıkarılıp yenisininki ekleniyor: replay aynı olayı
    yeniden işlediğinde toplam değişmiyor.
    """
    current = dict(current or {})
    total = int(current.get("total_reps", 0))
    if old_fact is not None:
        total -= int(old_fact.get("total_reps", 0))
    total += int(new_fact["total_reps"])

    best = current.get("best_clean_ratio")
    ratio = _clean_ratio(new_fact)
    if ratio is not None and (best is None or ratio > best):
        best = ratio

    minutes = set(current.get("started_minutes") or [])
    minutes.add(_epoch_minute(new_fact["started_at"]))

    return {
        "total_reps": total,
        "best_clean_ratio": best,
        "has_squat": bool(current.get("has_squat")) or new_fact["exercise_id"] == "squat",
        "started_minutes": sorted(minutes),
        "fact_count": int(current.get("fact_count", 0)) + (0 if old_fact is not None else 1),
        "updated_at": firestore.SERVER_TIMESTAMP,
    }


def summary_from_facts(facts: list[dict]) -> dict:
    summary: dict | None = None
    for fact in sorted(facts, key=lambda f: f["started_at"]):
        summary = fold_summary(summary, None, fact)
    return summary or {}


async def upsert_in_tx(tx, workout_id: uuid.UUID, fact: dict) -> None:
    """Fact + özet, çağıranın transaction'ında. Okumalar yazmalardan ÖNCE
    (Firestore transaction kuralı) — çağıran başka okuma yapacaksa önce yapmalı."""
    user_id = fact["user_id"]
    ref = fact_ref(user_id, workout_id)
    summary_ref = user_doc(user_id)
    old = await ref.get(transaction=tx)
    summary = await summary_ref.get(transaction=tx)
    tx.set(summary_ref, fold_summary(summary.to_dict() if summary.exists else None,
                                     old.to_dict() if old.exists else None, fact))
    tx.set(ref, {**fact, "projected_at": firestore.SERVER_TIMESTAMP})


async def rebuild_summary(user_id: uuid.UUID) -> dict:
    """Özeti kullanıcının tüm fact'lerinden SIFIRDAN kurar (bakım aracı).
    Maliyet: fact sayısı kadar okuma — istek yolunda ÇAĞRILMAZ."""
    facts = [snap.to_dict() async for snap in facts_col(user_id).stream()]
    summary = summary_from_facts(facts)
    await user_doc(user_id).set(summary)
    return summary


async def _facts_between(user_id: uuid.UUID, start_utc: datetime, end_utc: datetime) -> list[dict]:
    query = (
        facts_col(user_id)
        .where(filter=firestore.FieldFilter("started_at", ">=", start_utc))
        .where(filter=firestore.FieldFilter("started_at", "<", end_utc))
        .order_by("started_at")
    )
    return [snap.to_dict() async for snap in query.stream()]


async def fetch_daily(
    user_id: uuid.UUID,
    offset_minutes: int,
    start_utc: datetime,
    end_utc: datetime,
) -> list[ExerciseDayRow]:
    """Gün × egzersiz toplamları. Gün etiketi UTC zamana saat dilimi farkı
    EKLENEREK çıkarılıyor — workout-service `repo/stats.py` ile aynı kural."""
    offset = timedelta(minutes=offset_minutes)
    agg: dict[tuple[date, str], dict] = {}
    for fact in await _facts_between(user_id, start_utc, end_utc):
        key = ((fact["started_at"] + offset).date(), fact["exercise_id"])
        a = agg.setdefault(key, {"workouts": 0, "sets": 0, "reps": 0, "rwe": 0, "active": 0.0})
        a["workouts"] += 1
        a["sets"] += int(fact["total_sets"])
        a["reps"] += int(fact["total_reps"])
        a["rwe"] += int(fact["reps_with_errors"])
        a["active"] += float(fact["total_active_seconds"])
    return [
        ExerciseDayRow(
            local_date=day,
            exercise_id=exercise_id,
            workouts=a["workouts"],
            sets=a["sets"],
            reps=a["reps"],
            reps_with_errors=a["rwe"],
            active_seconds=a["active"],
        )
        for (day, exercise_id), a in sorted(agg.items())
    ]


async def fetch_error_counts(
    user_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
    exercise_id: str | None = None,
) -> tuple[list[ErrorCountRow], int, int]:
    """(hata sayıları — çoktan aza, toplam tekrar, hatalı tekrar).

    Postgres'te iki sorguydu (`jsonb_each_text` + toplam); burada aynı aralık
    okumasından ikisi birden çıkıyor.
    """
    counts: dict[str, int] = {}
    total_reps = 0
    reps_with_errors = 0
    for fact in await _facts_between(user_id, start_utc, end_utc):
        if exercise_id is not None and fact["exercise_id"] != exercise_id:
            continue
        total_reps += int(fact["total_reps"])
        reps_with_errors += int(fact["reps_with_errors"])
        for name, value in (fact.get("form_errors") or {}).items():
            counts[name] = counts.get(name, 0) + int(value)
    rows = [
        ErrorCountRow(error_name=name, occurrences=value)
        for name, value in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return rows, total_reps, reps_with_errors


async def fetch_badge_stats(user_id: uuid.UUID, offset_minutes: int) -> BadgeStats:
    """Tek doküman okuması (özet). Yerel saat/tarih burada, isteğin farkıyla."""
    snap = await user_doc(user_id).get()
    summary = snap.to_dict() if snap.exists else {}
    local_minutes = [m + offset_minutes for m in summary.get("started_minutes") or []]
    hours = {(m // 60) % 24 for m in local_minutes}
    dates = sorted({datetime.fromtimestamp(m * 60, tz=timezone.utc).date() for m in local_minutes})
    return BadgeStats(
        total_reps=int(summary.get("total_reps", 0)),
        best_clean_ratio=summary.get("best_clean_ratio"),
        has_squat=bool(summary.get("has_squat")),
        has_early_bird=any(h < 8 for h in hours),
        has_night_owl=any(h >= 22 for h in hours),
        active_local_dates=dates,
    )


async def delete_all(user_id: uuid.UUID) -> int:
    """Özet + tüm fact'ler (hesap silme)."""
    return await db.client.recursive_delete(user_doc(user_id))
