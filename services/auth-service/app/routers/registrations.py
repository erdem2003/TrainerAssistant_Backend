"""Kayit, kod dogrulama ve kod tekrar gonderme uclari."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Request, status

from app import events, security
from app.config import settings
from app.db import db
from app.errors import (
    code_expired,
    code_invalid,
    code_invalidated,
    code_not_found,
    email_already_registered,
    rate_limited,
)
from app.ratelimit import (
    limiter,
    register_email_key,
    register_ip_key,
    resend_email_key,
)
from app.repo import codes, outbox, users
from app.schemas import (
    AcceptedResponse,
    RegistrationRequest,
    ResendRequest,
    TokenPair,
    VerifyRequest,
)
from app.sessions import issue_token_pair

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth/registrations", tags=["registrations"])

HOUR = 3600
MINUTE = 60


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def register(payload: RegistrationRequest, request: Request) -> AcceptedResponse:
    """Kayıt — üç dal, tek yanıt."""
    email = security.normalize_email(payload.email)

    await limiter.hit(register_ip_key(_client_ip(request)),
                      settings.register_per_ip_per_hour, HOUR)
    await limiter.hit(register_email_key(email),
                      settings.register_per_email_per_hour, HOUR)

    # Parola hash'i transaction DIŞINDA hesaplanıyor: bcrypt ~250 ms sürüyor ve
    # o süre boyunca veritabanı bağlantısını tutmanın anlamı yok.
    password_hash = await security.hash_password(payload.password)
    code = security.generate_code()
    code_hash = await security.hash_code(code)

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            existing = await users.find_by_email(conn, email)

            # Doğrulanmış hesap: ürün kararıyla kullanıcı DOĞRUDAN
            # bilgilendiriliyor (bkz. errors.email_already_registered —
            # enumeration korumasından bilinçli vazgeçiş). Hiçbir şey
            # değiştirilmiyor ve artık sahibe ayrıca e-posta ATILMIYOR; kayıt
            # denemesini yapan zaten anında "hesap var" yanıtını görüyor.
            if existing is not None and existing.is_verified:
                raise email_already_registered()

            if existing is None:
                user = await users.insert_pending(conn, email, password_hash)
                await _issue_verification(conn, user.id, email, code_hash, code)

            else:
                updated = await users.overwrite_unverified(conn, existing.id, password_hash)
                if updated is not None:
                    await _issue_verification(conn, updated.id, email, code_hash, code)

    # Log'da e-posta YOK (service-contract §11).
    logger.info("kayıt isteği işlendi")
    return AcceptedResponse()


@router.post("/verify", response_model=TokenPair)
async def verify(payload: VerifyRequest) -> TokenPair:
    """Kod doğrulama."""
    email = security.normalize_email(payload.email)
    now = datetime.now(timezone.utc)

    async with db.pool.acquire() as conn:
        user = await users.find_by_email(conn, email)
        if user is None:
            raise code_not_found()

        active = await codes.find_active(conn, user.id, codes.PURPOSE_EMAIL_VERIFY)
        if active is None:
            raise code_not_found()

        if active.is_expired(now):
            await codes.invalidate(conn, active.id)
            raise code_expired()

        if await security.verify_code(payload.code, active.code_hash):
            async with conn.transaction():
                await codes.consume(conn, active.id)
                verified = await users.mark_verified(conn, user.id)
            target = verified or user
            logger.info("hesap doğrulandı user_id=%s", target.id)
            return await issue_token_pair(target.id, is_verified=True, device_label=None)

        # Yanlış kod: sayacı artır.
        attempts = await codes.increment_attempts(conn, active.id)
        if attempts >= settings.code_max_attempts:
            await codes.invalidate(conn, active.id)
            logger.warning("kod deneme sınırı aşıldı user_id=%s", user.id)
            raise code_invalidated()

        raise code_invalid()


@router.post("/resend", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def resend(payload: ResendRequest) -> AcceptedResponse:
    """Yeni doğrulama kodu — kullanıcı isteğiyle."""
    email = security.normalize_email(payload.email)
    await limiter.hit(resend_email_key(email), settings.resend_per_email_per_hour, HOUR)

    code = security.generate_code()
    code_hash = await security.hash_code(code)

    async with db.pool.acquire() as conn:
        user = await users.find_by_email(conn, email)

        # Kullanıcı yoksa ya da zaten doğrulanmışsa SESSİZCE aynı yanıt döner.
        if user is not None and not user.is_verified:
            last = await codes.last_issued_at(conn, user.id, codes.PURPOSE_EMAIL_VERIFY)
            if last is not None:
                elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                if elapsed < settings.resend_cooldown_seconds:
                    raise rate_limited(int(settings.resend_cooldown_seconds - elapsed))

            async with conn.transaction():
                await _issue_verification(conn, user.id, email, code_hash, code)

    return AcceptedResponse()

# ---------------------------------------------------------------------------


async def _issue_verification(
    conn: asyncpg.Connection,
    user_id,
    email: str,
    code_hash: str,
    code: str,
) -> None:
    """Kodu yazar ve e-posta isteğini outbox'a bırakır."""
    await codes.issue(conn, user_id, codes.PURPOSE_EMAIL_VERIFY, code_hash,
                      security.code_expiry())
    await outbox.enqueue(
        conn,
        events.EVENT_EMAIL_VERIFICATION_REQUESTED,
        events.TOPIC_AUTH_EMAIL,
        partition_key=str(user_id),
        payload={
            "email": email,
            "code": code,
            "expires_in_seconds": settings.code_ttl_seconds,
        },
    )
