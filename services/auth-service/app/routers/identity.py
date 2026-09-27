"""GET /v1/auth/me ve /v1/auth/introspect — kimlik sorgulama (ADR 0019).

Token doğrulama artık Firebase ID token'ı üzerinden, `nabiz_firebase.auth`'ta.
Tek süreçli dağıtımda `FirebaseAuthMiddleware` bunu her istekte yapıyor;
`/introspect` ayrı bir kapı (ör. harici bir gateway'in alt-isteği) için aynı
sözleşmeyle (204 + X-User-Id / X-Email-Verified / X-Token-Exp) duruyor.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Request, Response, status
from nabiz_firebase import auth as firebase_auth

from app.errors import ApiError
from app.repo import accounts
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


@router.get("/introspect", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def introspect(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    """Firebase ID token geçerli mi? Geçerliyse kimlik başlıklarıyla 204."""
    try:
        identity = await firebase_auth.verify_bearer(authorization)
    except firebase_auth.InvalidToken as exc:
        logger.info("geçersiz token: %s (uri=%s)", exc, request.headers.get("X-Original-URI", "-"))
        raise _unauthorized() from None
    if identity is None:
        raise _unauthorized()

    await firebase_auth.registry.ensure(identity)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            HEADER_USER_ID: str(identity.user_id),
            HEADER_EMAIL_VERIFIED: str(identity.email_verified).lower(),
            HEADER_TOKEN_EXP: str(identity.expires_at_ms),
        },
    )


@router.get("/me", response_model=MeResponse)
async def me(x_user_id: str | None = Header(default=None)) -> MeResponse:
    """Oturumdaki kullanıcı. Kimliği ara katmanın koyduğu başlıktan okur."""
    if not x_user_id:
        raise _unauthorized()
    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise _unauthorized() from None

    account = await accounts.find_by_id(user_id)
    if account is None:
        # Token geçerli ama hesap silinmiş (Firebase token'ı silmeden sonra
        # bitişine kadar geçerli kalır).
        raise _unauthorized()

    return MeResponse(
        id=str(account.id),
        email=account.email or "",
        email_verified=account.email_verified,
        status="ACTIVE" if account.email_verified else "PENDING_VERIFICATION",
        created_at=int(account.created_at.timestamp() * 1000),
    )
