"""Ortam degiskenleri: veritabani, Redis ve soket omru ayarlari."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "chat-service"
    log_level: str = "INFO"

    database_url: str = "postgresql://trainer:trainer@localhost:15433/chat_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # `DELETE /internal/users/{id}` ucunu koruyan paylaşılan sır.
    internal_api_key: str = ""

    # Sosyal bildirimlerin ve coklu-ornek dagitiminin surecler-arasi koprusu
    # (ADR 0014, "Redis pub/sub"). Redis zaten ayakta — auth-service hiz
    # sinirlamasi icin kullaniyor.
    redis_url: str = "redis://redis:6379/0"

    # ★ TEK SENKRON CAGRI NOKTASI ★ Arkadaslik/kullanici adi `social_db`'de
    # (ADR 0005), chat_db'de degil. Mesaj gonderirken yazma yetkisi (arkadas
    # mi), konusma listesinde ad gosterirken de profil bilgisi icin
    # `social-service/app/routers/internal.py`'deki iki uc cagrilir (Faz S6).
    social_service_url: str = "http://social-service:8000"

    # ★ SOKET OMRU UST SINIRI ★
    # `X-Token-Exp`'in kendisi zaten bir ust sinir sagliyor (erisim token'i
    # ~15 dk), ama bu sabit ikinci bir guvenlik agi: gateway'den beklenmeyen
    # bir deger gelirse (ornegin bos/hatali basaligi) soket YINE DE sonsuza
    # kadar acik kalmaz.
    ws_max_lifetime_seconds: int = 4 * 60 * 60

    # Istemcinin pingInterval'i (30s) ile uyumlu; iki kacirilmis ping sonrasi
    # olu baglanti sayilir (gateway `/ws` location'indaki proxy_read_timeout
    # 75s ile ayni gerekce).
    ws_idle_timeout_seconds: int = 75


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
