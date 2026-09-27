"""GET /v1/auth/me ve /v1/auth/introspect — kimlik sorgulama."""

from __future__ import annotations

import logging
import uuid

import jwt
from fastapi import APIRouter, Header, Request, Response, status

from app import security
from app.db import db
from app.errors import ApiError
from app.repo import users
from app.schemas import MeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["identity"])

HEADER_USER_ID = "X-User-Id"
HEADER_EMAIL_VERIFIED = "X-Email-Verified"
HEADER_TOKEN_EXP = "X-Token-Exp"


def _unauthorized() -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_TOKEN",
        "Oturum geçersiz, tekrar giriş yap",
    )


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _unauthorized()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    return token

# ---------------------------------------------------------------------------
# Gateway alt-isteği
# ---------------------------------------------------------------------------


@router.get("/introspect", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def introspect(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    """Token geçerli mi? Gateway'in `auth_request` alt-isteği buraya gelir."""
    token = _bearer_token(authorization)

    try:
        claims = security.decode_access_token(token)
    except jwt.ExpiredSignatureError:
        # Süresi dolmuş token normal bir durum (15 dakikada bir olur);
        # uyarı seviyesinde loglamak gürültü üretir.
        raise _unauthorized() from None
    except jwt.InvalidTokenError as exc:
        # İmza hatası, yanlış issuer/audience, bozuk token — bunlar normal değil.
        logger.warning("geçersiz token: %s (uri=%s)", exc,
                       request.headers.get("X-Original-URI", "-"))
        raise _unauthorized() from None

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            HEADER_USER_ID: claims["sub"],
            HEADER_EMAIL_VERIFIED: str(claims.get("email_verified", False)).lower(),
            # `exp` JWT standardında epoch SANIYE; sözleşme (§6) epoch
            # MILISANIYE istiyor — chat-service'in `/ws` el sıkışmasında
            # soket ömrünü sınırlaması için (ADR 0014, "Soket ömrü ve token
            # süresi"). chat-service bu sayıyı hiç yorumlamıyor, yalnızca
            # o ana geldiğinde bağlantıyı kapatıyor — JWT çözümü burada,
            # tek yerde kalıyor (service-contract §2).
            HEADER_TOKEN_EXP: str(claims["exp"] * 1000),
        },
    )

# ---------------------------------------------------------------------------
# Korumalı ürün ucu — deseni gösteren örnek
# ---------------------------------------------------------------------------


@router.get("/me", response_model=MeResponse)
async def me(x_user_id: str | None = Header(default=None)) -> MeResponse:
    """Oturumdaki kullanıcı."""
    if not x_user_id:
        # Gateway'siz doğrudan çağrı. Üretimde ulaşılmaz olmalı.
        raise _unauthorized()

    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        # Başlık UUID değil. Gateway her zaman geçerli bir UUID yazar, yani bu
        # ancak servise doğrudan erişilirse olur. Ayrıştırmadan sorguya
        # göndermek asyncpg'de patlar ve 401 yerine 500 dönerdi.
        raise _unauthorized() from None

    async with db.pool.acquire() as conn:
        user = await users.find_by_id(conn, user_id)

    if user is None:
        # Token geçerli ama kullanıcı silinmiş.
        raise _unauthorized()

    return MeResponse(
        id=str(user.id),
        email=user.email,
        email_verified=user.is_verified,
        status=user.status,
        created_at=int(user.created_at.timestamp() * 1000),
    )
