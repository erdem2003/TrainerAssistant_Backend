"""Ortam degiskenleri: olay akisi, tuketici ve depolama ayarlari (ADR 0019)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "social-service"
    log_level: str = "INFO"

    # `DELETE /internal/users/{id}` ucunu koruyan paylaşılan sır.
    internal_api_key: str = ""

    # --- Olay akisi (Kafka yerine Firestore outbox dagiticisi) ---------------
    # `workout-service/app/events.py`'deki sabitle AYNI olmali — iki yerde
    # duruyor cunku servisler kod paylasmiyor (ADR 0005).
    topic_workout_session: str = "workout.session"

    # ★ CONSUMER GROUP ADI ★ `analytics-workout-v1`'den KASITLI FARKLI: her
    # grup kendi teslim durumunu tutar, biri digerinin hatasindan etkilenmez.
    consumer_group: str = "social-workout-v1"

    # ★ REPLAY MODU ★ Acikken `processed_events` kontrolu ATLANIYOR —
    # `analytics-service`'teki ayni mekanizma (Phase 11 cikis kriteri).
    replay_mode: bool = False

    # Bekleyen gonderi supurucusunun araligi. Bos sorgu da 1 okuma sayiliyor:
    # 10 dk → gunde 144 okuma (Kafka dalinda 60 sn idi).
    pending_sweep_seconds: float = 600.0

    # Firebase Storage kovasi `nabiz_firebase.admin`'de (FIREBASE_STORAGE_BUCKET).


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
