"""Ortam degiskenleri: social-service adresi ve soket omru ayarlari (ADR 0019)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "chat-service"
    log_level: str = "INFO"

    # `DELETE /internal/users/{id}` ucunu koruyan paylaşılan sır.
    internal_api_key: str = ""

    # ★ TEK SENKRON CAGRI NOKTASI ★ Arkadaslik/kullanici adi social-service'te
    # (ADR 0005). Mesaj gonderirken yazma yetkisi (arkadas mi), konusma
    # listesinde ad gosterirken profil bilgisi icin iki ic uc cagrilir.
    # Tek surecli dagitimda `social_client.use_transport()` ile ag atlanabilir.
    social_service_url: str = "http://social-service:8000"

    # ★ SOKET OMRU UST SINIRI ★ (`/ws` — artik yalnizca canli ortak antrenman
    # rolesi icin; sohbet ve bildirimler Firestore dinleyicisinde.)
    ws_max_lifetime_seconds: int = 4 * 60 * 60
    ws_idle_timeout_seconds: int = 75


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
