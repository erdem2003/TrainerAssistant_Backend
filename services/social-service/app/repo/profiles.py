"""Sosyal profil CRUD — kullanici adi, gorunen ad, avatar, opt-in bayragi."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import asyncpg

_UPSERT_DEFAULT = """
INSERT INTO social_profiles (user_id, username, display_name, avatar_seed, social_enabled)
VALUES ($1, $2, $2, $3, false)
ON CONFLICT (user_id) DO NOTHING
"""

_CLAIM_USERNAME = """
UPDATE social_profiles
   SET username = $2, display_name = $3, social_enabled = true, updated_at = now()
 WHERE user_id = $1
"""

_FIND_BY_USER_ID = """
SELECT user_id, username, display_name, avatar_seed, social_enabled, created_at
  FROM social_profiles
 WHERE user_id = $1
"""

_USERNAME_TAKEN = """
SELECT 1 FROM social_profiles WHERE lower(username) = lower($1) AND user_id != $2
UNION ALL
SELECT 1 FROM retired_usernames WHERE username_lower = lower($1)
LIMIT 1
"""

# ★ İLİŞKİ DURUMU TEK SORGUDA ★ (ADR 0017'nin arkadaşlık-istegi hatasını
# kapatan yarısı) — arama sonucu sunucu tarafında kendiyle birleşen bir
# `friendships` satırı taşımıyordu, mobil taraf da başarı/hata geri bildirimi
# göstermiyordu; kullanıcı "Ekle"ye bastığında (a) kendi adını arayıp kendine
# istek göndermeye çalışıyor ya da (b) zaten arkadaş/PENDING olan birine
# tekrar basıyor olabiliyordu — ikisi de sunucuda sessizce yutulan bir hataya
# düşüyordu. Sonuç artık `relationship_status` taşıyor, istemci "Ekle"
# butonunu duruma göre gösterip gizliyor.
_SEARCH = """
SELECT sp.user_id, sp.username, sp.display_name, sp.avatar_seed,
       f.status AS friendship_status, f.requested_by AS friendship_requested_by
  FROM social_profiles sp
  LEFT JOIN friendships f
    ON f.user_low = LEAST(sp.user_id, $3) AND f.user_high = GREATEST(sp.user_id, $3)
 WHERE sp.social_enabled AND sp.user_id != $3 AND lower(sp.username) LIKE lower($1) || '%'
 ORDER BY sp.username
 LIMIT $2
"""

_RETIRE_USERNAME = """
INSERT INTO retired_usernames (username_lower) VALUES (lower($1))
ON CONFLICT (username_lower) DO NOTHING
"""

_DELETE_PROFILE = "DELETE FROM social_profiles WHERE user_id = $1"

_FIND_BY_USER_IDS = """
SELECT user_id, username, display_name, avatar_seed, social_enabled, created_at
  FROM social_profiles WHERE user_id = ANY($1::uuid[])
"""


@dataclass(frozen=True)
class SocialProfile:
    user_id: uuid.UUID
    username: str
    display_name: str
    avatar_seed: str
    social_enabled: bool
    created_at: object


async def ensure_placeholder(conn: asyncpg.Connection, user_id: uuid.UUID, fallback_name: str) -> None:
    """Kullanicinin ilk `/v1/social/*` cagrisinda bir satiri olmasini garantiler.

    Kullanici adi HENUZ ALINMAMIS olabilir — bu durumda `social_enabled=false`
    ve gecici bir kullanici adi (kendi UUID'si) atanir. Boylece `friendships`
    gibi tablolar hep var olan bir `user_id`'ye FOREIGN KEY olmadan referans
    verebilir (ADR 0005: veritabani basina servis, capraz-servis FK yok).
    """
    await conn.execute(_UPSERT_DEFAULT, user_id, fallback_name, str(user_id))


async def is_username_taken(conn: asyncpg.Connection, username: str, user_id: uuid.UUID) -> bool:
    row = await conn.fetchrow(_USERNAME_TAKEN, username, user_id)
    return row is not None


async def claim_username(
    conn: asyncpg.Connection, user_id: uuid.UUID, username: str, display_name: str
) -> None:
    await conn.execute(_CLAIM_USERNAME, user_id, username, display_name)


async def find_by_user_id(conn: asyncpg.Connection, user_id: uuid.UUID) -> SocialProfile | None:
    row = await conn.fetchrow(_FIND_BY_USER_ID, user_id)
    if row is None:
        return None
    return SocialProfile(**dict(row))


async def search(
    conn: asyncpg.Connection, query: str, limit: int, viewer_id: uuid.UUID
) -> list[asyncpg.Record]:
    """Ham satır döner (`SocialProfile`'a sarmalanmıyor) — çağıran taraf
    (`app/routers/profiles.py`) `friendship_status`/`friendship_requested_by`
    alanlarından `relationship_status`'u kendisi türetiyor."""
    return await conn.fetch(_SEARCH, query, limit, viewer_id)


async def find_by_user_ids(conn: asyncpg.Connection, user_ids: list[uuid.UUID]) -> list[SocialProfile]:
    """`chat-service`'in konuşma listesini yazar/görünen ad ile göstermesi
    için (Faz S6) — chat_db'de profil yok, sohbetin her açılışında N ayrı
    çağrı yerine TEK toplu çağrı (`/internal/profiles/batch`)."""
    rows = await conn.fetch(_FIND_BY_USER_IDS, user_ids)
    return [SocialProfile(**dict(row)) for row in rows]


async def delete_and_retire(conn: asyncpg.Connection, user_id: uuid.UUID) -> None:
    """Hesap silme: profili siler, kullanici adini 30 gunluk sogumaya alir."""
    profile = await find_by_user_id(conn, user_id)
    if profile is not None:
        await conn.execute(_RETIRE_USERNAME, profile.username)
    await conn.execute(_DELETE_PROFILE, user_id)
