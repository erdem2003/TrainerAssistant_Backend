"""users tablosunun SQL'i."""

from __future__ import annotations

import uuid
from datetime import datetime

import asyncpg

# ---------------------------------------------------------------------------

FIND_BY_EMAIL = """
SELECT id, email, password_hash, email_verified_at, status, created_at, updated_at
  FROM users
 WHERE email = $1
"""

FIND_BY_ID = """
SELECT id, email, password_hash, email_verified_at, status, created_at, updated_at
  FROM users
 WHERE id = $1
"""

INSERT_PENDING = """
INSERT INTO users (email, password_hash, status)
VALUES ($1, $2, 'PENDING_VERIFICATION')
RETURNING id, email, password_hash, email_verified_at, status, created_at, updated_at
"""

# Doğrulanmamış hesabın parolasını ÜZERİNE YAZAR.
OVERWRITE_UNVERIFIED = """
UPDATE users
   SET password_hash = $2,
       updated_at    = now()
 WHERE id = $1
   AND email_verified_at IS NULL
RETURNING id, email, password_hash, email_verified_at, status, created_at, updated_at
"""

# Parola degistirme — YALNIZCA DOGRULANMIS hesaplarda.
UPDATE_PASSWORD = """
UPDATE users
   SET password_hash = $2,
       updated_at    = now()
 WHERE id = $1
   AND email_verified_at IS NOT NULL
RETURNING id, email, password_hash, email_verified_at, status, created_at, updated_at
"""

# Hesap silme — GERI DONUSU YOK.
DELETE_BY_ID = """
DELETE FROM users
 WHERE id = $1
RETURNING id, email
"""

MARK_VERIFIED = """
UPDATE users
   SET email_verified_at = now(),
       status            = 'ACTIVE',
       updated_at        = now()
 WHERE id = $1
   AND email_verified_at IS NULL
RETURNING id, email, password_hash, email_verified_at, status, created_at, updated_at
"""

# ---------------------------------------------------------------------------


class User:
    """asyncpg satırının okunabilir sarmalayıcısı."""

    __slots__ = ("id", "email", "password_hash", "email_verified_at", "status",
                 "created_at", "updated_at")

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: uuid.UUID = row["id"]
        self.email: str = row["email"]
        self.password_hash: str = row["password_hash"]
        self.email_verified_at: datetime | None = row["email_verified_at"]
        self.status: str = row["status"]
        self.created_at: datetime = row["created_at"]
        self.updated_at: datetime = row["updated_at"]

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


def _wrap(row: asyncpg.Record | None) -> User | None:
    return User(row) if row is not None else None


async def find_by_email(conn: asyncpg.Connection, email: str) -> User | None:
    return _wrap(await conn.fetchrow(FIND_BY_EMAIL, email))


async def find_by_id(conn: asyncpg.Connection, user_id: uuid.UUID) -> User | None:
    return _wrap(await conn.fetchrow(FIND_BY_ID, user_id))


async def insert_pending(
    conn: asyncpg.Connection, email: str, password_hash: str
) -> User:
    return User(await conn.fetchrow(INSERT_PENDING, email, password_hash))


async def overwrite_unverified(
    conn: asyncpg.Connection, user_id: uuid.UUID, password_hash: str
) -> User | None:
    """`None` dönerse hesap bu arada doğrulanmış demektir — yarış durumu."""
    return _wrap(await conn.fetchrow(OVERWRITE_UNVERIFIED, user_id, password_hash))


async def mark_verified(conn: asyncpg.Connection, user_id: uuid.UUID) -> User | None:
    return _wrap(await conn.fetchrow(MARK_VERIFIED, user_id))


async def update_password(
    conn: asyncpg.Connection, user_id: uuid.UUID, password_hash: str
) -> User | None:
    """`None` donerse hesap dogrulanmamis demektir."""
    return _wrap(await conn.fetchrow(UPDATE_PASSWORD, user_id, password_hash))


async def delete_by_id(conn: asyncpg.Connection, user_id: uuid.UUID) -> str | None:
    """Hesabi siler. Silinen kullanicinin e-postasini doner, yoksa `None`."""
    row = await conn.fetchrow(DELETE_BY_ID, user_id)
    return row["email"] if row else None
