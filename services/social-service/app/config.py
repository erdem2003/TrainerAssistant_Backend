"""Ortam degiskenleri: veritabani, Redis, Kafka ve tuketici ayarlari."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "social-service"
    log_level: str = "INFO"

    database_url: str = "postgresql://trainer:trainer@localhost:15433/social_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # `DELETE /internal/users/{id}` ucunu koruyan paylaşılan sır.
    internal_api_key: str = ""

    # chat-service'e bildirim uyandirma sinyali icin (ADR 0014, "Redis
    # pub/sub"). Faz S6'da kullaniliyor.
    redis_url: str = "redis://redis:6379/0"

    # --- Kafka (Faz S3'te devreye giriyor) ----------------------------------
    kafka_bootstrap: str = "redpanda:9092"

    # `workout-service/app/events.py`'deki sabitle AYNI olmali — iki yerde
    # duruyor cunku servisler kod paylasmiyor (ADR 0005).
    topic_workout_session: str = "workout.session"

    # ★ CONSUMER GROUP ADI ★ `analytics-workout-v1`'den KASITLI FARKLI: her
    # servis kendi offset'ini tutar, biri digerinin tuketim hizindan
    # etkilenmez (ADR 0014, "workout_snapshots projeksiyonu").
    consumer_group: str = "social-workout-v1"

    # ★ REPLAY MODU ★ Acikken `processed_events` kontrolu ATLANIYOR —
    # `analytics-service`'teki ayni mekanizma (Phase 11 cikis kriteri).
    replay_mode: bool = False

    retry_seconds: float = 2.0

    # --- MinIO (Faz S12 — motivasyon gönderisi fotoğrafları, ADR 0016) -------
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "trainer"
    minio_secret_key: str = "trainer123"
    minio_bucket: str = "social-photos"
    minio_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
