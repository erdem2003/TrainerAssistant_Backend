"""Refresh token rotasyonu ve yeniden kullanim tespiti."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app import security
from app.db import db
from app.errors import invalid_refresh_token
from app.repo import tokens
from app.schemas import TokenPair

logger = logging.getLogger(__name__)


async def issue_token_pair(
    user_id: uuid.UUID,
    is_verified: bool,
    device_label: str | None,
    family_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
) -> TokenPair:
    """Yeni access + refresh çifti."""
    access_token, expires_in = security.create_access_token(user_id, is_verified)

    refresh_token = security.generate_refresh_token()
    refresh_hash = security.hash_refresh_token(refresh_token)

    async with db.pool.acquire() as conn:
        await tokens.insert(
            conn,
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            parent_id=parent_id,
            token_hash=refresh_hash,
            expires_at=security.refresh_expiry(),
            device_label=device_label,
        )

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


async def rotate(refresh_token: str) -> TokenPair:
    """Yenileme + yeniden kullanım tespiti."""
    token_hash = security.hash_refresh_token(refresh_token)
    now = datetime.now(timezone.utc)

    async with db.pool.acquire() as conn:
        stored = await tokens.find_by_hash(conn, token_hash)

        if stored is None or stored.is_expired(now):
            raise invalid_refresh_token()

        if stored.is_used:
            # YENİDEN KULLANIM. Hangi kopyanın saldırganda olduğunu bilemeyiz,
            # bu yüzden zincirin tamamı düşer.
            async with conn.transaction():
                await tokens.revoke_family(
                    conn, stored.family_id, tokens.REASON_REUSE_DETECTED
                )
            logger.warning(
                "refresh token yeniden kullanıldı, aile iptal edildi user_id=%s family=%s",
                stored.user_id,
                stored.family_id,
            )
            raise invalid_refresh_token()

        if stored.revoked_at is not None:
            raise invalid_refresh_token()

        # `mark_rotated` yalnızca `used_at IS NULL` iken günceller. Eşzamanlı iki
        # yenileme isteğinde biri kazanır, diğeri buraya düşer ve yeniden
        # kullanım olarak işlenir — doğru davranış, çünkü biri saldırgan olabilir.
        if not await tokens.mark_rotated(conn, stored.id):
            async with conn.transaction():
                await tokens.revoke_family(
                    conn, stored.family_id, tokens.REASON_REUSE_DETECTED
                )
            logger.warning("eşzamanlı yenileme yarışı, aile iptal edildi user_id=%s",
                           stored.user_id)
            raise invalid_refresh_token()

    from app.repo import users  # döngüsel import olmasın diye burada

    async with db.pool.acquire() as conn:
        user = await users.find_by_id(conn, stored.user_id)

    if user is None:
        raise invalid_refresh_token()

    return await issue_token_pair(
        user_id=stored.user_id,
        is_verified=user.is_verified,
        device_label=stored.device_label,
        family_id=stored.family_id,   # ZİNCİR SÜRÜYOR
        parent_id=stored.id,
    )


async def revoke(refresh_token: str) -> None:
    """Logout — o cihazın zinciri kapanır."""
    token_hash = security.hash_refresh_token(refresh_token)

    async with db.pool.acquire() as conn:
        stored = await tokens.find_by_hash(conn, token_hash)
        if stored is None:
            return
        async with conn.transaction():
            await tokens.revoke_family(conn, stored.family_id, tokens.REASON_LOGOUT)

    logger.info("oturum kapatıldı user_id=%s", stored.user_id)
