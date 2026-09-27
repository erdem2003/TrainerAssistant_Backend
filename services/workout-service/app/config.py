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

    # --- Firestore outbox dagiticisi (ADR 0019) ------------------------------
    # Yoklama YEDEK yol: yeni olay commit'ten hemen sonra `notify()` ile
    # dagitiliyor. Bos yoklama da 1 okuma sayildigi icin aralik uzun — 60 sn
    # gunde ~1.440 okuma (ucretsiz kota 50k/gun). Gerekce: nabiz_firebase/outbox.py.
    outbox_poll_seconds: float = 60.0
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 5
    # Dagiticiyi bu surecte baslat. Tek surecli dagitimda yalnizca BIR yerde
    # acik olmali; ayni koleksiyonu iki surec dagitirsa teslim yine
    # idempotent ama bosuna iki kat okuma olur.
    outbox_dispatcher_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
