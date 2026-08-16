"""verification_codes tablosunun SQL'i."""

from __future__ import annotations

import uuid
from datetime import datetime

import asyncpg

# ---------------------------------------------------------------------------

# Aynı anda tek aktif kod olabilir (kısmi UNIQUE index). Yeni kod üretmeden önce
# eskisi geçersiz kılınır; iki geçerli kodun dolaşması deneme sayacını anlamsız
# kılardı — saldırgan her kod için ayrı 3 hak kazanırdı.
INVALIDATE_ACTIVE = """
UPDATE verification_codes
   SET invalidated_at = now()
 WHERE user_id = $1
   AND purpose = $2
   AND consumed_at    IS NULL
   AND invalidated_at IS NULL
"""

INSERT = """
INSERT INTO verification_codes (user_id, purpose, code_hash, expires_at)
VALUES ($1, $2, $3, $4)
RETURNING id, user_id, purpose, code_hash, expires_at, attempts,
          consumed_at, invalidated_at, created_at
"""

FIND_ACTIVE = """
SELECT id, user_id, purpose, code_hash, expires_at, attempts,
       consumed_at, invalidated_at, created_at
  FROM verification_codes
 WHERE user_id = $1
   AND purpose = $2
   AND consumed_at    IS NULL
   AND invalidated_at IS NULL
"""

# Deneme sayacı ARTIRILIR ve yeni değer geri döner. Sayacı uygulamada tutup
# ayrıca yazmak yerine tek sorguda yapılıyor: iki eşzamanlı deneme arasında
# sayacın kaybolmaması için.
INCREMENT_ATTEMPTS = """
UPDATE verification_codes
   SET attempts = attempts + 1
 WHERE id = $1
RETURNING attempts
"""

INVALIDATE_BY_ID = """
UPDATE verification_codes
   SET invalidated_at = now()
 WHERE id = $1
"""

CONSUME = """
UPDATE verification_codes
   SET consumed_at = now()
 WHERE id = $1
   AND consumed_at IS NULL
RETURNING id
"""

# Son üretim zamanı — "60 saniye bekle" kuralı için. Redis'teki hız sınırına ek
# olarak veritabanında da kontrol ediliyor: Redis düşerse kural kaybolmasın.
LAST_ISSUED_AT = """
SELECT created_at
  FROM verification_codes
 WHERE user_id = $1
   AND purpose = $2
 ORDER BY created_at DESC
 LIMIT 1
"""

# ---------------------------------------------------------------------------


class VerificationCode:
    __slots__ = ("id", "user_id", "purpose", "code_hash", "expires_at",
                 "attempts", "consumed_at", "invalidated_at", "created_at")

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: uuid.UUID = row["id"]
        self.user_id: uuid.UUID = row["user_id"]
        self.purpose: str = row["purpose"]
        self.code_hash: str = row["code_hash"]
        self.expires_at: datetime = row["expires_at"]
        self.attempts: int = row["attempts"]
        self.consumed_at: datetime | None = row["consumed_at"]
        self.invalidated_at: datetime | None = row["invalidated_at"]
        self.created_at: datetime = row["created_at"]

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now

PURPOSE_EMAIL_VERIFY = "EMAIL_VERIFY"
PURPOSE_PASSWORD_RESET = "PASSWORD_RESET"


async def issue(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    purpose: str,
    code_hash: str,
    expires_at: datetime,
) -> VerificationCode:
    """Eskisini geçersiz kılıp yenisini yazar. Çağıran taraf transaction açar."""
    await conn.execute(INVALIDATE_ACTIVE, user_id, purpose)
    return VerificationCode(await conn.fetchrow(INSERT, user_id, purpose, code_hash, expires_at))


async def find_active(
    conn: asyncpg.Connection, user_id: uuid.UUID, purpose: str
) -> VerificationCode | None:
    row = await conn.fetchrow(FIND_ACTIVE, user_id, purpose)
    return VerificationCode(row) if row else None


async def increment_attempts(conn: asyncpg.Connection, code_id: uuid.UUID) -> int:
    return await conn.fetchval(INCREMENT_ATTEMPTS, code_id)


async def invalidate(conn: asyncpg.Connection, code_id: uuid.UUID) -> None:
    await conn.execute(INVALIDATE_BY_ID, code_id)


async def consume(conn: asyncpg.Connection, code_id: uuid.UUID) -> bool:
    return await conn.fetchval(CONSUME, code_id) is not None


async def last_issued_at(
    conn: asyncpg.Connection, user_id: uuid.UUID, purpose: str
) -> datetime | None:
    return await conn.fetchval(LAST_ISSUED_AT, user_id, purpose)
