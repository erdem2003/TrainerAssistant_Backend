"""Giris, token yenileme ve cikis uclari."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status

from app import security
from app.config import settings
from app.db import db
from app.errors import email_not_verified, invalid_credentials
from app.ratelimit import limiter, login_email_key, login_ip_key
from app.repo import users
from app.schemas import LoginRequest, LogoutRequest, RefreshRequest, TokenPair
from app.sessions import issue_token_pair, revoke, rotate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth/sessions", tags=["sessions"])

MINUTE = 60


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request) -> TokenPair:
    """Giriş."""
    email = security.normalize_email(payload.email)

    await limiter.hit(login_ip_key(_client_ip(request)),
                      settings.login_per_ip_per_minute, MINUTE)
    await limiter.hit(login_email_key(email),
                      settings.login_per_email_per_minute, MINUTE)

    async with db.pool.acquire() as conn:
        user = await users.find_by_email(conn, email)

    # `user is None` durumunda da doğrulama çalışır (sabit zaman).
    stored_hash = user.password_hash if user is not None else None
    if not await security.verify_password(payload.password, stored_hash):
        logger.info("başarısız giriş denemesi")
        raise invalid_credentials()

    assert user is not None  # hash doğrulandıysa kullanıcı vardır

    if not user.is_verified:
        raise email_not_verified()

    if user.status == "DISABLED":
        raise invalid_credentials()

    logger.info("giriş başarılı user_id=%s", user.id)
    return await issue_token_pair(
        user_id=user.id,
        is_verified=True,
        device_label=payload.device_label,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest) -> TokenPair:
    """Yenileme — rotasyon + yeniden kullanım tespiti (`app/sessions.py`)."""
    return await rotate(payload.refresh_token)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest) -> Response:
    await revoke(payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
