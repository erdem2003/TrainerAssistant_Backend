"""Pydantic istek/yanit govdeleri."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.security import BCRYPT_MAX_BYTES, CODE_DIGITS

# Parola alt sınırı. 8 karakter NIST'in tavsiye ettiği taban.
MIN_PASSWORD_LENGTH = 8


class RegistrationRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, value: str) -> str:
        """bcrypt 72 BAYTTAN sonrasını SESSİZCE KESER."""
        if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(f"parola en fazla {BCRYPT_MAX_BYTES} bayt olabilir")
        return value


class VerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=CODE_DIGITS, max_length=CODE_DIGITS)

    @field_validator("code")
    @classmethod
    def _digits_only(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("kod yalnızca rakamlardan oluşur")
        return value


class ResendRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Kullanıcı "hangi cihazlarda açığım" görebilsin diye. Zorunlu değil.
    device_label: str | None = Field(default=None, max_length=100)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str

# --- Yanıtlar ---------------------------------------------------------------


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    # Saniye cinsinden. İstemci bunu kullanarak süresi dolmadan yenileyebilir.
    expires_in: int


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    code: str = Field(min_length=CODE_DIGITS, max_length=CODE_DIGITS)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)

    @field_validator("code")
    @classmethod
    def _digits_only(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("kod yalnızca rakamlardan oluşur")
        return value

    @field_validator("new_password")
    @classmethod
    def _fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(f"parola en fazla {BCRYPT_MAX_BYTES} bayt olabilir")
        return value


class PasswordChangeRequest(BaseModel):
    """Oturum açıkken parola değiştirme."""

    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(f"parola en fazla {BCRYPT_MAX_BYTES} bayt olabilir")
        return value


class AccountDeleteRequest(BaseModel):
    """Hesap silme — parola doğrulaması ister."""

    password: str


class MeResponse(BaseModel):
    """Oturumdaki kullanıcı — `GET /v1/auth/me`."""

    id: str
    email: str
    email_verified: bool
    status: str
    # UTC epoch milisaniye (service-contract §6) — mobil taraf da böyle saklıyor.
    created_at: int


class AcceptedResponse(BaseModel):
    """Kayıt ve tekrar gönderme yanıtı."""

    status: str = "accepted"
    message: str = "Doğrulama kodu e-posta adresine gönderildi"
