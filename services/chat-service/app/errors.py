"""Tek tip hata bicimi (service-contract §3) ve sik kullanilan hatalar."""

from __future__ import annotations

import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.correlation import current_correlation_id

logger = logging.getLogger(__name__)


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


def invalid_token() -> ApiError:
    """`X-User-Id` yok ya da UUID değil."""
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_TOKEN",
        "Oturum geçersiz, tekrar giriş yap",
    )


def forbidden() -> ApiError:
    return ApiError(
        status.HTTP_403_FORBIDDEN,
        "FORBIDDEN",
        "Bu kaynağa erişim yetkin yok",
    )


def unprocessable(message: str, details: dict | None = None) -> ApiError:
    """Şema doğru ama iş kuralı ihlal edildi — service-contract §3, 422."""
    return ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "UNPROCESSABLE", message, details)


def not_found(message: str = "Kayıt bulunamadı") -> ApiError:
    """404. Başkasının kaynağı için de 404 dönülür, 403 değil (service-contract §3)."""
    return ApiError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", message)


def conflict(message: str, details: dict | None = None) -> ApiError:
    """409 — aynı doğal anahtar FARKLI içerikle geldi (service-contract §4)."""
    return ApiError(status.HTTP_409_CONFLICT, "CONFLICT", message, details)

# --- FastAPI bağlantısı ------------------------------------------------------


async def api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Sözleşmeye uygun hata yanıtı."""
    if not isinstance(exc, ApiError):
        return await unhandled_error_handler(_, exc)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "correlation_id": current_correlation_id(),
            }
        },
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Beklenmeyen hata."""
    logger.exception("beklenmeyen hata", exc_info=exc)
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
