"""Ortam degiskenleri: veritabani, Redis, JWT, SMTP, sureler, hiz sinirlari.
Sirlar koddan degil .env'den gelir."""

from __future__ import annotations

from email.utils import parseaddr
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "auth-service"
    log_level: str = "INFO"

    database_url: str = "postgresql://trainer:trainer@localhost:5433/auth_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    redis_url: str = "redis://localhost:6380/0"

    # --- JWT ---
    # RS256, HS256 DEĞİL: gateway token'ı yalnızca PUBLIC key ile doğrular,
    jwt_private_key_path: str = "/run/secrets/jwt_private.pem"
    jwt_public_key_path: str = "/run/secrets/jwt_public.pem"
    jwt_issuer: str = "trainer-asistant-auth"
    jwt_audience: str = "trainer-asistant"

    access_token_ttl_seconds: int = 15 * 60          # 15 dakika
    refresh_token_ttl_seconds: int = 30 * 24 * 3600  # 30 gün

    # --- Doğrulama kodu ---
    code_ttl_seconds: int = 10 * 60
    code_max_attempts: int = 3

    # --- Hız sınırları ---
    # Değerler service-contract'taki tabloyla aynı.
    login_per_email_per_minute: int = 5
    login_per_ip_per_minute: int = 20
    register_per_email_per_hour: int = 3
    register_per_ip_per_hour: int = 10
    resend_cooldown_seconds: int = 60
    resend_per_email_per_hour: int = 5

    # --- SMTP ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    mail_from: str = "AI Fitness Coach <no-reply@trainerasistant.local>"

    @field_validator("mail_from")
    @classmethod
    def _check_mail_from(cls, value: str) -> str:
        """`MAIL_FROM`'un ayrıştırılabilir bir adres olduğunu doğrular."""
        _, address = parseaddr(value)
        if "@" not in address or address.startswith("@") or address.endswith("@"):
            raise ValueError(
                f"MAIL_FROM ayrıştırılamadı: {value!r}. "
                'Beklenen biçim: "Görünen Ad <hesap@example.com>" '
                "veya düz \"hesap@example.com\"."
            )
        return value

    @field_validator("smtp_password")
    @classmethod
    def _strip_app_password(cls, value: str | None) -> str | None:
        """Gmail uygulama parolasındaki boşlukları temizler."""
        if value is None:
            return None
        return "".join(value.split())

    # --- Servisler arası (Phase 10 köprüsü, Phase 11'de Kafka olacak) ---
    # Hesap silindiğinde user-service'e haber vermek için. Ayrıntılı gerekçe:
    # app/worker/fanout.py
    user_service_url: str = "http://user-service:8000"
    workout_service_url: str = "http://workout-service:8000"
    health_service_url: str = "http://health-service:8000"
    internal_api_key: str = ""

    # Worker'ın outbox'ı tarama sıklığı. Kısa tutuluyor: kullanıcı kayıt olduktan
    # sonra doğrulama kodunu bekliyor ve 5 saniye bile uzun hissettirir.
    outbox_poll_seconds: float = 1.0
    outbox_batch_size: int = 20
    outbox_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
