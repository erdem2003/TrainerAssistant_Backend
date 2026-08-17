"""Pydantic istek/yanit govdeleri ve icerik ozeti (content hash).

Sema, mobil taraftaki core/workout/WorkoutRecord.kt sozlesmesinin karsiligidir.
Zaman damgalari epoch milisaniye (service-contract §6), sureler saniye (Float).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, time, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

# FormError enum'i mobil tarafta tanimli (core/pose/FormRules.kt). Burada
# LISTE OLARAK tekrar edilmiyor: yeni bir hata turu eklendiginde iki tarafi
# birden guncellemek gerekirdi ve biri unutulurdu. Sunucu yalnizca BICIMI
# dogruluyor — anlamini bilen taraf istemci ve analytics-service.
_FORM_ERROR_MAX_LEN = 64


def epoch_ms(value: datetime | None) -> int | None:
    """service-contract §6: UTC epoch milisaniye."""
    return None if value is None else int(value.timestamp() * 1000)


def from_epoch_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


class RepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    duration_seconds: float = Field(ge=0)
    eccentric_seconds: float = Field(ge=0)
    concentric_seconds: float = Field(ge=0)
    rom: float = Field(ge=0, le=1)
    form_errors: list[str] = Field(default_factory=list)

    @field_validator("form_errors")
    @classmethod
    def _check_errors(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item or len(item) > _FORM_ERROR_MAX_LEN:
                raise ValueError("Geçersiz form hatası adı")
            if not item.replace("_", "").isalnum() or item != item.upper():
                # SCREAMING_SNAKE bekleniyor (service-contract §7).
                raise ValueError("Form hatası SCREAMING_SNAKE olmalı")
        # Aynı hata iki kez gelirse veritabanı birincil anahtarı reddederdi;
        # burada sessizce tekilleştirmek daha bağışlayıcı ve zararsız.
        return sorted(set(value))


class SetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    started_at: int
    ended_at: int
    reps: list[RepIn]

    @field_validator("reps")
    @classmethod
    def _check_reps(cls, value: list[RepIn]) -> list[RepIn]:
        indexes = [rep.index for rep in value]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Tekrar sıraları benzersiz olmalı")
        return value


class WorkoutIn(BaseModel):
    """`POST /v1/workouts` gövdesi.

    `id` İSTEMCİDE üretilir. Aynı id ikinci kez gelirse yeni kayıt açılmaz;
    ağ hatasında tekrar denemek güvenli olmak zorunda (service-contract §4).
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    exercise_id: str = Field(min_length=1, max_length=64)
    started_at: int
    ended_at: int | None = None
    sets: list[SetIn]

    @field_validator("sets")
    @classmethod
    def _check_sets(cls, value: list[SetIn]) -> list[SetIn]:
        if not value:
            raise ValueError("En az bir set gerekli")
        indexes = [item.index for item in value]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Set sıraları benzersiz olmalı")
        return value

    def content_hash(self) -> str:
        """Gövdenin içerik özeti — aynı id farklı içerikle gelirse 409 için.

        SIRA BAĞIMSIZ: setler ve tekrarlar `index`'e göre sıralanıyor, form
        hataları da alfabetik. Aynı antrenman farklı sırada gönderilirse aynı
        özeti üretmeli; yoksa istemcinin serileştirme sırası değiştiğinde
        sahte bir çakışma üretilirdi.

        `ended_at` özete DAHİL: yarım bırakılmış bir antrenmanın sonradan
        tamamlanmış hâli farklı bir içeriktir ve çakışma olarak görünmeli.
        """
        canonical = {
            "exercise_id": self.exercise_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "sets": [
                {
                    "index": s.index,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "reps": [
                        {
                            "index": r.index,
                            "duration_seconds": round(r.duration_seconds, 3),
                            "eccentric_seconds": round(r.eccentric_seconds, 3),
                            "concentric_seconds": round(r.concentric_seconds, 3),
                            "rom": round(r.rom, 4),
                            "form_errors": r.form_errors,
                        }
                        for r in sorted(s.reps, key=lambda x: x.index)
                    ],
                }
                for s in sorted(self.sets, key=lambda x: x.index)
            ],
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- Yanıtlar ---------------------------------------------------------------

class RepOut(BaseModel):
    index: int
    duration_seconds: float
    eccentric_seconds: float
    concentric_seconds: float
    rom: float
    form_errors: list[str]


class SetOut(BaseModel):
    index: int
    started_at: int
    ended_at: int
    rep_count: int
    reps: list[RepOut]


class WorkoutOut(BaseModel):
    id: str
    exercise_id: str
    started_at: int
    ended_at: int | None
    total_sets: int
    total_reps: int
    sets: list[SetOut]


class WorkoutSummary(BaseModel):
    """Liste yanıtı — setler ve tekrarlar DAHİL DEĞİL.

    Geçmiş listesi 50 antrenman döndüğünde her birinin tüm tekrarlarını
    göndermek yanıtı gereksiz büyütürdü. Ayrıntı için `GET /v1/workouts/{id}`.
    """

    id: str
    exercise_id: str
    started_at: int
    ended_at: int | None
    total_sets: int
    total_reps: int
    reps_with_errors: int
    # Setlerin toplam süresi, setler ARASI dinlenme hariç.
    #
    # Kalori tahmini bu alanı gerektiriyor ve `ended_at - started_at` yerine
    # kullanılmak zorunda: antrenmanın baştan sona süresi setler arası
    # dinlenmeyi de kapsıyor, o da tahmini birkaç kat şişiriyor
    # (`core/health/HealthMetrics.estimatedCalories` dokümantasyonu).
    total_active_seconds: float
    # Bu antrenmandaki en kalabalık setin tekrar sayısı.
    #
    # Kişisel rekor ("tek sette en çok tekrar") liste yanıtından hesaplanabilsin
    # diye burada: set kırılımı `WorkoutSummary`'de yok ve her antrenmanın
    # ayrıntısını çekmek 200 istek demekti.
    best_set_reps: int


class WorkoutPage(BaseModel):
    items: list[WorkoutSummary]
    next_cursor: str | None


class ExerciseOut(BaseModel):
    id: str
    display_name: str
    required_view: str


# --- Günlük program ---------------------------------------------------------

class PlanItemIn(BaseModel):
    """`PUT /v1/plan` gövdesindeki tek kalem."""

    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(min_length=1, max_length=64)
    # Üst sınır veritabanındaki `plan_items_target_range` kısıtıyla aynı.
    # İki yerde duruyor çünkü Pydantic hatası alan adını söyler, veritabanı
    # kısıtı ise anlaşılmaz bir 500 üretirdi.
    target_reps: int = Field(ge=1, le=1000)
    # "08:30" — opsiyonel. Alarm KURULMUYOR, yalnızca kart üstünde gösteriliyor.
    scheduled_time: time | None = None


class PlanDayIn(BaseModel):
    """Bir günün TAM listesi. Kısmi güncelleme yok."""

    model_config = ConfigDict(extra="forbid")

    items: list[PlanItemIn]

    @field_validator("items")
    @classmethod
    def _check_items(cls, value: list[PlanItemIn]) -> list[PlanItemIn]:
        ids = [item.exercise_id for item in value]
        if len(ids) != len(set(ids)):
            # Veritabanındaki `plan_items_unique_exercise` de reddederdi ama
            # oradan gelen hata kullanıcıya "hangi egzersiz" demezdi.
            raise ValueError("Aynı egzersiz bir güne iki kez eklenemez")
        if len(value) > _PLAN_MAX_ITEMS:
            raise ValueError(f"Bir güne en fazla {_PLAN_MAX_ITEMS} kalem eklenebilir")
        return value


class PlanItemOut(BaseModel):
    """Hedef ve GERÇEKLEŞEN birlikte.

    `done_reps` ve `completed` veritabanında saklanmıyor; o günün antrenman
    kayıtlarından hesaplanıyor. Karşılaştırmayı sunucu yapıyor ki üç istemci
    ekranı (anasayfa, Schedule, success kontrolü) aynı kuralı üç kez
    yazmasın — biri diğerlerinden ayrılırdı.
    """

    id: str
    exercise_id: str
    target_reps: int
    done_reps: int
    scheduled_time: time | None
    completed: bool


class PlanDayOut(BaseModel):
    date: str
    items: list[PlanItemOut]
    # Kalem yoksa `completed` FALSE: boş bir program "tamamlandı" sayılsaydı
    # hiç plan yapmamış kullanıcı her antrenman sonrası success ekranı görürdü.
    completed: bool


class PlanDaySummary(BaseModel):
    """Gün şeridi işareti — kalem ayrıntısı olmadan."""

    date: str
    item_count: int
    completed_count: int
    completed: bool


class PlanRangeOut(BaseModel):
    days: list[PlanDaySummary]


# Bir güne konabilecek en fazla kalem. Katalogda iki egzersiz var; sınır
# kötüye kullanıma karşı, kullanıcıyı kısıtlamak için değil.
_PLAN_MAX_ITEMS = 20


# --- Günlük toplamlar (İstatistik ekranı) -----------------------------------

class ExerciseDayOut(BaseModel):
    """Bir günün tek egzersize ait kırılımı.

    `active_seconds` EGZERSİZ BAŞINA ayrı duruyor çünkü kalori hesabı MET
    gerektiriyor ve MET egzersize göre değişiyor. Günün toplam süresini tek sayı
    olarak vermek, şınav ile mekiği aynı MET'le hesaplamaya zorlardı.
    """

    exercise_id: str
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float


class DayStatsOut(BaseModel):
    date: str
    workouts: int
    sets: int
    reps: int
    reps_with_errors: int
    active_seconds: float
    by_exercise: list[ExerciseDayOut]
    # `FormError` adı → o gün kaç tekrarda görüldü.
    form_errors: dict[str, int]


class DailyStatsOut(BaseModel):
    """Yalnızca VERİSİ OLAN günler döner; boş günler yok.

    Aralıktaki her günü sıfırlarla doldurmak yanıtı şişirirdi ve istemci
    grafiği çizerken boş günleri zaten kendi ekliyor (tarih ekseni onda).
    """

    days: list[DayStatsOut]
