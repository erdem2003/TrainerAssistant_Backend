"""Pydantic yanit govdeleri.

ADR 0019: kayit/giris/yenileme/parola/kod istek govdeleri (RegistrationRequest,
LoginRequest, RefreshRequest, PasswordReset*, VerifyRequest, AccountDeleteRequest,
TokenPair, AcceptedResponse) KALKTI — kimlik Firebase Auth'ta, hesap silme
govdesiz (istemci Firebase ile yeniden kimlik dogruladiktan sonra cagiriyor).
Onceki surum git gecmisinde.
"""

from __future__ import annotations

from pydantic import BaseModel


class MeResponse(BaseModel):
    """Oturumdaki kullanıcı — `GET /v1/auth/me`. Biçim DEĞİŞMEDİ."""

    id: str
    email: str
    email_verified: bool
    # PENDING_VERIFICATION | ACTIVE — Postgres'teki `users.status`'un
    # karşılığı, Firebase'in `email_verified` bayrağından türetiliyor.
    status: str
    # UTC epoch milisaniye (service-contract §6) — mobil taraf da böyle saklıyor.
    created_at: int
