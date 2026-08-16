"""refresh_tokens tablosunun SQL'i."""

from __future__ import annotations

import uuid
from datetime import datetime

import asyncpg

# ---------------------------------------------------------------------------

INSERT = """
INSERT INTO refresh_tokens (user_id, family_id, parent_id, token_hash, expires_at, device_label)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, user_id, family_id, parent_id, token_hash, issued_at, expires_at,
          used_at, revoked_at, revoked_reason, device_label
"""

FIND_BY_HASH = """
SELECT id, user_id, family_id, parent_id, token_hash, issued_at, expires_at,
       used_at, revoked_at, revoked_reason, device_label
  FROM refresh_tokens
 WHERE token_hash = $1
"""

# Rotasyon: token kullanıldı olarak işaretlenir.
MARK_ROTATED = """
UPDATE refresh_tokens
   SET used_at        = now(),
       revoked_at     = now(),
       revoked_reason = 'ROTATED'
 WHERE id = $1
   AND used_at IS NULL
RETURNING id
"""

# AİLENİN TAMAMINI İPTAL ET.
REVOKE_FAMILY = """
UPDATE refresh_tokens
   SET revoked_at     = now(),
       revoked_reason = $2
 WHERE family_id = $1
   AND revoked_at IS NULL
"""

REVOKE_ALL_FOR_USER = """
UPDATE refresh_tokens
   SET revoked_at     = now(),
       revoked_reason = $2
 WHERE user_id = $1
   AND revoked_at IS NULL
"""

# Süresi geçmişleri temizleme — periyodik bakım işi için hazır.
DELETE_EXPIRED = """
DELETE FROM refresh_tokens
 WHERE expires_at < now() - INTERVAL '30 days'
"""

# ---------------------------------------------------------------------------

REASON_ROTATED = "ROTATED"
REASON_LOGOUT = "LOGOUT"
REASON_REUSE_DETECTED = "REUSE_DETECTED"
REASON_PASSWORD_CHANGED = "PASSWORD_CHANGED"


class RefreshToken:
    __slots__ = ("id", "user_id", "family_id", "parent_id", "token_hash",
                 "issued_at", "expires_at", "used_at", "revoked_at",
                 "revoked_reason", "device_label")

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: uuid.UUID = row["id"]
        self.user_id: uuid.UUID = row["user_id"]
        self.family_id: uuid.UUID = row["family_id"]
        self.parent_id: uuid.UUID | None = row["parent_id"]
        self.token_hash: str = row["token_hash"]
        self.issued_at: datetime = row["issued_at"]
        self.expires_at: datetime = row["expires_at"]
        self.used_at: datetime | None = row["used_at"]
        self.revoked_at: datetime | None = row["revoked_at"]
        self.revoked_reason: str | None = row["revoked_reason"]
        self.device_label: str | None = row["device_label"]

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now

    @property
    def is_used(self) -> bool:
        """Zaten rotate edilmiş. Tekrar sunulması yeniden kullanım demektir."""
        return self.used_at is not None


async def insert(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    token_hash: str,
    expires_at: datetime,
    device_label: str | None,
) -> RefreshToken:
    return RefreshToken(
        await conn.fetchrow(
            INSERT, user_id, family_id, parent_id, token_hash, expires_at, device_label
        )
    )


async def find_by_hash(conn: asyncpg.Connection, token_hash: str) -> RefreshToken | None:
    row = await conn.fetchrow(FIND_BY_HASH, token_hash)
    return RefreshToken(row) if row else None


async def mark_rotated(conn: asyncpg.Connection, token_id: uuid.UUID) -> bool:
    """`False` dönerse başka bir istek bu token'ı zaten kullanmış demektir."""
    return await conn.fetchval(MARK_ROTATED, token_id) is not None


async def revoke_family(
    conn: asyncpg.Connection, family_id: uuid.UUID, reason: str
) -> None:
    await conn.execute(REVOKE_FAMILY, family_id, reason)


async def revoke_all_for_user(
    conn: asyncpg.Connection, user_id: uuid.UUID, reason: str
) -> None:
    await conn.execute(REVOKE_ALL_FOR_USER, user_id, reason)
