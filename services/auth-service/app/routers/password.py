"""Parola sifirlama (kod ile) ve parola degistirme uclari."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Header, status

from app import events, security
from app.config import settings
from app.db import db
from app.errors import (
    ApiError,
    code_expired,
    code_invalid,
    code_invalidated,
    code_not_found,
    invalid_credentials,
    rate_limited,
)
from app.ratelimit import limiter, resend_email_key
from app.repo import codes, outbox, tokens, users
from app.schemas import (
    AcceptedResponse,
    PasswordChangeRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    TokenPair,
)
from app.sessions import issue_token_pair

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["password"])

HOUR = 3600


def _unauthorized() -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_TOKEN",
        "Oturum geçersiz, tekrar giriş yap",
    )

# ---------------------------------------------------------------------------
# Sıfırlama isteği
# ---------------------------------------------------------------------------


@router.post(
    "/password-resets",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedResponse,
)
async def request_reset(payload: PasswordResetRequest) -> AcceptedResponse:
    """Sıfırlama kodu iste."""
    email = security.normalize_email(payload.email)

    # Kod tekrar gönderme ile aynı sınır: e-posta bombalama bu ucun da en somut
    # kötüye kullanım yolu.
    await limiter.hit(resend_email_key(email), settings.resend_per_email_per_hour, HOUR)

    code = security.generate_code()
    code_hash = await security.hash_code(code)

    async with db.pool.acquire() as conn:
        user = await users.find_by_email(conn, email)

        if user is not None and user.is_verified:
            last = await codes.last_issued_at(conn, user.id, codes.PURPOSE_PASSWORD_RESET)
            if last is not None:
                elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                if elapsed < settings.resend_cooldown_seconds:
                    raise rate_limited(int(settings.resend_cooldown_seconds - elapsed))

            async with conn.transaction():
                await codes.issue(
                    conn, user.id, codes.PURPOSE_PASSWORD_RESET,
                    code_hash, security.code_expiry(),
                )
                await outbox.enqueue(
                    conn,
                    events.EVENT_PASSWORD_RESET_REQUESTED,
                    events.TOPIC_AUTH_EMAIL,
                    partition_key=str(user.id),
                    payload={
                        "email": email,
                        "code": code,
                        "expires_in_seconds": settings.code_ttl_seconds,
                    },
                )

    logger.info("parola sıfırlama isteği işlendi")
    return AcceptedResponse(message="Sıfırlama kodu e-posta adresine gönderildi")

# ---------------------------------------------------------------------------
# Sıfırlamayı tamamla
# ---------------------------------------------------------------------------


@router.post("/password-resets/confirm", response_model=TokenPair)
async def confirm_reset(payload: PasswordResetConfirm) -> TokenPair:
    """Kod + yeni parola → parola değişir, tüm oturumlar kapanır."""
    email = security.normalize_email(payload.email)
    now = datetime.now(timezone.utc)

    async with db.pool.acquire() as conn:
        user = await users.find_by_email(conn, email)
        if user is None or not user.is_verified:
            raise code_not_found()

        active = await codes.find_active(conn, user.id, codes.PURPOSE_PASSWORD_RESET)
        if active is None:
            raise code_not_found()

        if active.is_expired(now):
            await codes.invalidate(conn, active.id)
            raise code_expired()

        if not await security.verify_code(payload.code, active.code_hash):
            attempts = await codes.increment_attempts(conn, active.id)
            if attempts >= settings.code_max_attempts:
                await codes.invalidate(conn, active.id)
                logger.warning("sıfırlama kodu deneme sınırı aşıldı user_id=%s", user.id)
                raise code_invalidated()
            raise code_invalid()

        new_hash = await security.hash_password(payload.new_password)
        await _apply_new_password(conn, user.id, email, new_hash, active.id)

    logger.info("parola sıfırlandı user_id=%s", user.id)
    return await issue_token_pair(user.id, is_verified=True, device_label=None)

# ---------------------------------------------------------------------------
# Oturum açıkken parola değiştirme
# ---------------------------------------------------------------------------


@router.put("/password", response_model=TokenPair)
async def change_password(
    payload: PasswordChangeRequest,
    x_user_id: str | None = Header(default=None),
) -> TokenPair:
    """Giriş yapmış kullanıcı parolasını değiştirir."""
    if not x_user_id:
        raise _unauthorized()
    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise _unauthorized() from None

    async with db.pool.acquire() as conn:
        user = await users.find_by_id(conn, user_id)
        if user is None:
            raise _unauthorized()

        if not await security.verify_password(payload.current_password, user.password_hash):
            logger.info("parola değiştirme: mevcut parola hatalı user_id=%s", user_id)
            raise invalid_credentials()

        new_hash = await security.hash_password(payload.new_password)
        await _apply_new_password(conn, user_id, user.email, new_hash, None)

    logger.info("parola değiştirildi user_id=%s", user_id)
    # Tüm oturumlar kapandı; kullanıcı uygulamadan atılmasın diye yeni çift.
    return await issue_token_pair(user_id, is_verified=True, device_label=None)

# ---------------------------------------------------------------------------


async def _apply_new_password(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    email: str,
    new_hash: str,
    code_id: uuid.UUID | None,
) -> None:
    """Parolayı yaz, kodu tüket, TÜM OTURUMLARI KAPAT, bilgi maili kuyruğa al."""
    async with conn.transaction():
        await users.update_password(conn, user_id, new_hash)

        if code_id is not None:
            await codes.consume(conn, code_id)

        # Saldırganın elindeki refresh token'lar burada ölüyor.
        await tokens.revoke_all_for_user(conn, user_id, tokens.REASON_PASSWORD_CHANGED)

        await outbox.enqueue(
            conn,
            events.EVENT_PASSWORD_CHANGED,
            events.TOPIC_AUTH_EMAIL,
            partition_key=str(user_id),
            payload={"email": email},
        )
