"""Ortam degiskenleri: veritabani ve servisler-arasi API anahtari."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "user-service"
    log_level: str = "INFO"

    database_url: str = "postgresql://trainer:trainer@localhost:15433/user_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # `DELETE /internal/users/{id}` ucunu koruyan paylaşılan sır.
    internal_api_key: str = ""

    # Başka serviste etkisi olan ödüllerin (lig kalkanı, 2x XP, ekstra görev)
    # iletileceği adresler — `app/reward_forward.py`. Boşsa ödül iletilemez.
    social_service_url: str = ""
    workout_service_url: str = ""

    # Davet ödülü: davet edilen ilk antrenmanını bitirince (WorkoutCompleted).
    topic_workout_session: str = "workout.session"
    referral_consumer_group: str = "user-referral-v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
