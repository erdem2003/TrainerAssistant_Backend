"""Ortam degiskenleri: veritabani, Kafka ve tuketici ayarlari."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "analytics-service"
    log_level: str = "INFO"

    database_url: str = "postgresql://trainer:trainer@localhost:5433/analytics_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    internal_api_key: str = ""

    # --- Kafka --------------------------------------------------------------
    kafka_bootstrap: str = "redpanda:9092"

    # Topic adi `workout-service/app/events.py`'deki sabitle AYNI olmali.
    # Iki yerde duruyor cunku servisler kod paylasmiyor (ADR 0005); degisirse
    # ikisi birden degismeli.
    topic_workout_session: str = "workout.session"

    # ★ CONSUMER GROUP ADI ★
    # Offset bu ada bagli. Replay'in bir yolu offset'i sifirlamak, digeri bu adi
    # degistirmek — yeni bir group akisi bastan okur.
    consumer_group: str = "analytics-workout-v1"

    # ★ REPLAY MODU ★
    # Acikken `processed_events` kontrolu ATLANIYOR: normal calismada tekrari
    # yutmak isteniyor, replay'de ise tam tersi — her olay guncel mantikla
    # yeniden islenmeli.
    replay_mode: bool = False

    # Yazma hatasindan sonra beklenen sure; kuyrugu bosuna dondurmemek icin.
    retry_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
