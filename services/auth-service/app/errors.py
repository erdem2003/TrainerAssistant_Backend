"""Tek tip hata bicimi (service-contract §3) ve sik kullanilan hatalar."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.correlation import current_correlation_id


class ApiError(Exception):
    """Sözleşmeye uygun hata. Servisin her hatası bunun üzerinden çıkar."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

# --- Sık kullanılanlar -------------------------------------------------------
# Mesajlar Türkçe (kullanıcıya gösterilebilir), kodlar sabit ve İngilizce.


def invalid_credentials() -> ApiError:
    """Bilinmeyen e-posta ve yanlış parola AYNI hatayı döner."""
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_CREDENTIALS",
        "E-posta veya parola hatalı",
    )


def email_not_verified() -> ApiError:
    """Parola DOĞRU ama hesap doğrulanmamış."""
    return ApiError(
        status.HTTP_403_FORBIDDEN,
        "EMAIL_NOT_VERIFIED",
        "E-posta adresin henüz doğrulanmadı",
    )


def code_invalid() -> ApiError:
    return ApiError(
        status.HTTP_400_BAD_REQUEST,
        "CODE_INVALID",
        "Doğrulama kodu hatalı",
    )


def code_expired() -> ApiError:
    return ApiError(
        status.HTTP_400_BAD_REQUEST,
        "CODE_EXPIRED",
        "Doğrulama kodunun süresi doldu, yeni kod iste",
    )


def code_invalidated() -> ApiError:
    """3 yanlış denemeden sonra."""
    return ApiError(
        status.HTTP_400_BAD_REQUEST,
        "CODE_INVALIDATED",
        "Çok fazla yanlış deneme yaptın, yeni kod iste",
    )


def code_not_found() -> ApiError:
    return ApiError(
        status.HTTP_400_BAD_REQUEST,
        "CODE_NOT_FOUND",
        "Bekleyen bir doğrulama kodu yok",
    )


def invalid_refresh_token() -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_REFRESH_TOKEN",
        "Oturum geçersiz, tekrar giriş yap",
    )


def email_already_registered() -> ApiError:
    """Doğrulanmış bir hesaba kayıt denemesi.

    ★ ENUMERATION KORUMASINDAN BİLİNÇLİ VAZGEÇİŞ ★
    Önceki tasarım her durumda aynı 202 yanıtını dönüyordu (enumeration
    koruması) ve yalnızca hesap sahibine e-posta atıyordu. Ürün kararıyla bu
    değiştirildi: kullanıcı kayıt ekranında DOĞRUDAN bilgilendiriliyor, sahibe
    ayrıca e-posta ATILMIYOR (bkz. registrations.py, mailer.py'den kaldırılan
    `_existing_account_message`). Bilinen bedel: bu uç artık hangi e-postaların
    kayıtlı olduğunu denenerek öğrenmeye açık.
    """
    return ApiError(
        status.HTTP_409_CONFLICT,
        "EMAIL_ALREADY_REGISTERED",
        "Bu e-postaya ait bir hesap zaten var",
    )


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "RATE_LIMITED",
        "Çok fazla deneme yaptın, biraz bekle",
        {"retry_after_seconds": retry_after},
    )

# --- FastAPI bağlantısı ------------------------------------------------------


async def api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Sözleşmeye uygun hata yanıtı."""
    if not isinstance(exc, ApiError):
        # Ulaşılmaz: bu işleyici yalnızca ApiError için kayıtlı. Yine de sessiz
        # kalmak yerine genel işleyiciye devrediliyor.
        return await unhandled_error_handler(_, exc)

    body = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "correlation_id": current_correlation_id(),
        }
    }
    headers = {}
    if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        retry = exc.details.get("retry_after_seconds")
        if retry is not None:
            headers["Retry-After"] = str(retry)
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Beklenmeyen hata."""
    import logging

    logging.getLogger(__name__).exception("beklenmeyen hata", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Beklenmeyen bir hata oluştu",
                "details": {},
                "correlation_id": current_correlation_id(),
            }
        },
    )
