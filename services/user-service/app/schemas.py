"""Pydantic istek/yanit govdeleri ve enum'lar."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Sex(StrEnum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    # Kullanıcı belirtmek istemiyorsa bu değeri seçebilir. `null` ile farkı:
    # `null` "henüz sorulmadı", UNSPECIFIED "soruldu, paylaşmak istemedi".
    UNSPECIFIED = "UNSPECIFIED"


class Goal(StrEnum):
    """Figma onboarding Step3'teki dört seçenek (node 3:1599)."""

    MUSCLE_GAIN = "MUSCLE_GAIN"            # Strength Training for Muscle Gain
    FAT_LOSS_HIIT = "FAT_LOSS_HIIT"        # High-Intensity Interval Training
    FAT_LOSS_CARDIO = "FAT_LOSS_CARDIO"    # Cardiovascular Exercise
    FUNCTIONAL = "FUNCTIONAL"              # Functional Training


class UnitSystem(StrEnum):
    METRIC = "METRIC"      # kg · cm
    IMPERIAL = "IMPERIAL"  # lb · inch

# Yaş sınırları. Alt sınır 13: COPPA/KVKK açısından çocuk verisi işlemek ayrı bir
# yükümlülük sınıfı ve bu proje onu karşılamıyor. Üst sınır 120: doğrulanmış en
# yaşlı insan 122 yaşındaydı; bunun ötesi veri giriş hatasıdır.
MIN_AGE_YEARS = 13
MAX_AGE_YEARS = 120


class ProfileUpdate(BaseModel):
    """`PUT /v1/users/me` gövdesi — TAM DEĞİŞTİRME."""

    model_config = ConfigDict(extra="forbid")

    sex: Sex | None = None
    age: int | None = Field(default=None, ge=MIN_AGE_YEARS, le=MAX_AGE_YEARS)
    weight_kg: float | None = Field(default=None, ge=20, le=350)
    height_cm: float | None = Field(default=None, ge=80, le=260)
    goal: Goal | None = None
    unit_system: UnitSystem = UnitSystem.METRIC
    daily_goal_reps: int = Field(default=20, ge=1, le=1000)

    # İstemci onboarding'i bitirdiğinde `true` gönderir. Sunucu zaman damgasını
    # KENDİ koyar: istemci saatinin doğru olduğuna güvenmek, yanlış ayarlı bir
    # telefonun profili 2035'te tamamlanmış göstermesi demek olurdu.
    onboarding_completed: bool = False


class ProfileResponse(BaseModel):
    """`GET` ve `PUT` yanıtı."""

    user_id: str
    sex: Sex | None
    age: int | None
    weight_kg: float | None
    height_cm: float | None
    goal: Goal | None
    unit_system: UnitSystem
    daily_goal_reps: int
    onboarding_completed_at: int | None
    created_at: int | None
    updated_at: int | None
