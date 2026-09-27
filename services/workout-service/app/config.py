"""Ortam degiskenleri: veritabani ve servisler-arasi API anahtari."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "workout-service"
    log_level: str = "INFO"

    database_url: str = "postgresql://trainer:trainer@localhost:15433/workout_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # `DELETE /internal/users/{id}` ucunu koruyan paylasilan sir.
    # Asil koruma ag katmaninda: bu uc gateway'de hic yayinlanmiyor.
    internal_api_key: str = ""

    # Sayfalama — service-contract §5.
    page_size_default: int = 50
    page_size_max: int = 200

    # --- Outbox relay (Phase 11) --------------------------------------------
    # Degerler `auth-service` ile ayni: iki relay ayni deseni izliyor ve farkli
    # ayarlarda calismalarinin bir gerekcesi yok.
    kafka_bootstrap: str = "redpanda:9092"
    outbox_poll_seconds: float = 1.0
    outbox_batch_size: int = 20
    outbox_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
