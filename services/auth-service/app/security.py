"""bcrypt parola hash'leme, RS256 JWT uretme/dogrulama, token uretimi."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import bcrypt
import jwt

from app.config import settings

# bcrypt maliyet katsayısı. 12 güncel taban; her artış hash süresini ikiye katlar.
BCRYPT_ROUNDS = 12

# bcrypt girdiyi 72 BAYTTAN sonra SESSİZCE KESER. 72 bayttan uzun parolalarda
# fazlası yok sayılır — kullanıcı 100 karakterlik parola girdiğini sanır ama
BCRYPT_MAX_BYTES = 72

# Kullanıcı bulunamadığında doğrulanan sahte hash.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(BCRYPT_ROUNDS))

# --- Parola ------------------------------------------------------------------


def _hash_password_sync(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise ValueError("parola 72 bayttan uzun")
    return bcrypt.hashpw(raw, bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def _verify_password_sync(password: str, hashed: str | None) -> bool:
    raw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    if hashed is None:
        # Sabit zaman: sonucu atıyoruz ama hesabı yapıyoruz.
        bcrypt.checkpw(raw, _DUMMY_HASH)
        return False
    return bcrypt.checkpw(raw, hashed.encode("ascii"))


async def hash_password(password: str) -> str:
    """bcrypt CPU-yoğun (~250 ms). Event loop'u bloklamamak için thread'e alınır."""
    return await asyncio.to_thread(_hash_password_sync, password)


async def verify_password(password: str, hashed: str | None) -> bool:
    return await asyncio.to_thread(_verify_password_sync, password, hashed)

# --- Doğrulama kodu ----------------------------------------------------------

CODE_DIGITS = 6


def generate_code() -> str:
    """6 haneli doğrulama kodu."""
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


async def hash_code(code: str) -> str:
    """Kod da bcrypt ile hash'lenir."""
    return await hash_password(code)


async def verify_code(code: str, hashed: str) -> bool:
    return await verify_password(code, hashed)

# --- Refresh token -----------------------------------------------------------


def generate_refresh_token() -> str:
    """32 bayt kriptografik rastgelelik, URL-güvenli."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 — bcrypt DEĞİL."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

# --- JWT ---------------------------------------------------------------------


@lru_cache
def _private_key() -> str:
    return Path(settings.jwt_private_key_path).read_text(encoding="utf-8")


@lru_cache
def _public_key() -> str:
    return Path(settings.jwt_public_key_path).read_text(encoding="utf-8")


def create_access_token(user_id: uuid.UUID, email_verified: bool) -> tuple[str, int]:
    """RS256 imzalı access token."""
    now = datetime.now(timezone.utc)
    ttl = settings.access_token_ttl_seconds
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
        "email_verified": email_verified,
    }
    return jwt.encode(payload, _private_key(), algorithm="RS256"), ttl


def decode_access_token(token: str) -> dict:
    """Doğrulama. Bu serviste yalnızca testler için; asıl doğrulama gateway'de."""
    return jwt.decode(
        token,
        _public_key(),
        algorithms=["RS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )


def refresh_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        seconds=settings.refresh_token_ttl_seconds
    )


def code_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.code_ttl_seconds)


def normalize_email(email: str) -> str:
    """E-posta tek biçime indirgenir."""
    return email.strip().lower()
