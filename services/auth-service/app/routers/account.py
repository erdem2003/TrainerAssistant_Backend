"""DELETE /v1/auth/account — hesap silme. Token yetmez, parola da istenir."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Response, status

from app import events, security
from app.db import db
from app.errors import ApiError, invalid_credentials
from app.repo import outbox, users
from app.schemas import AccountDeleteRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["account"])


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    payload: AccountDeleteRequest,
    x_user_id: str | None = Header(default=None),
) -> Response:
    """Hesabı kalıcı olarak siler."""
    if not x_user_id:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_TOKEN",
            "Oturum geçersiz, tekrar giriş yap",
        )

    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_TOKEN",
            "Oturum geçersiz, tekrar giriş yap",
        ) from None

    async with db.pool.acquire() as conn:
        user = await users.find_by_id(conn, user_id)
        if user is None:
            # Zaten silinmiş. Silme isteğinin sonucu istenen durum olduğu için
            # hata değil, başarı dönüyoruz (idempotent).
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        if not await security.verify_password(payload.password, user.password_hash):
            logger.warning("hesap silme reddedildi: parola hatalı user_id=%s", user_id)
            raise invalid_credentials()

        async with conn.transaction():
            # Event ÖNCE kuyruğa alınıyor, satır sonra siliniyor — ikisi aynı
            # transaction'da. Ters sırada olsaydı `RETURNING` ile alınan e-posta
            deleted_email = await users.delete_by_id(conn, user_id)

            await outbox.enqueue(
                conn,
                events.EVENT_ACCOUNT_DELETED,
                events.TOPIC_AUTH_ACCOUNT,
                partition_key=str(user_id),
                payload={"user_id": str(user_id), "email": deleted_email},
            )

    logger.info("hesap silindi user_id=%s", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
