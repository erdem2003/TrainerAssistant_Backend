"""posts / post_likes / post_comments SQL (ADR 0014, Faz S4).

Beğeni/yorum SAYISI hiçbir yerde saklanmıyor (ADR 0012) — feed ve yorum
sayısı sorgu anında `COUNT()` ile hesaplanıyor.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import asyncpg

_INSERT_POST = """
INSERT INTO posts (id, author_id, workout_id, note, status, post_type, photo_content_type)
VALUES ($1, $2, $3, $4, $5, $6, $7)
"""

_FIND_POST_BY_ID = """
SELECT id, author_id, workout_id, note, status, created_at, post_type, photo_content_type
  FROM posts WHERE id = $1
"""

# Snapshot ZATEN varsa ve yazara aitse hızlı yol: gönderi hemen VISIBLE.
# Snapshot başkasınaysa (uydurma workout_id) ya da hiç yoksa çağıran taraf
# (router) PENDING_SNAPSHOT ile devam eder — ikinci durumda tüketici
# (workout_consumer.promote_pending) ya da süpürücü sonucu belirler.
_FIND_SNAPSHOT_OWNER = "SELECT user_id FROM workout_snapshots WHERE workout_id = $1"

# ★ TERFİ ★ `workout_consumer.py`, her snapshot upsert'inden SONRA çağırır.
# `author_id` eşleşmesi ZORUNLU: başkasının workout_id'siyle açılan bir
# gönderi asla VISIBLE olamaz (ADR 0014 karar #2'nin doğal sonucu).
_PROMOTE_PENDING = """
UPDATE posts SET status = 'VISIBLE'
 WHERE workout_id = $1 AND author_id = $2 AND status = 'PENDING_SNAPSHOT'
RETURNING id
"""

_DELETE_STALE_PENDING = """
DELETE FROM posts
 WHERE status = 'PENDING_SNAPSHOT' AND created_at < now() - interval '15 minutes'
RETURNING id
"""

_DELETE_POST = "DELETE FROM posts WHERE id = $1 AND author_id = $2 RETURNING id"

_SELECT_PHOTO_POST_IDS_BY_AUTHOR = """
SELECT id FROM posts WHERE author_id = $1 AND photo_content_type IS NOT NULL
"""

_DELETE_POSTS_BY_AUTHOR = "DELETE FROM posts WHERE author_id = $1"
_DELETE_LIKES_BY_USER = "DELETE FROM post_likes WHERE user_id = $1"
_DELETE_COMMENTS_BY_AUTHOR = "DELETE FROM post_comments WHERE author_id = $1"

# ★ FEED — HERKESE AÇIK (ADR 0017) ★ Yalnızca VISIBLE, sosyali açık HERKESİN
# gönderisi — arkadaşlık filtresi YOK. Sahibin ilk isteği ("Twitter tarzı")
# başta yalnızca gönderi TÜRÜNE (metin+foto) uygulanmıştı, görünürlük ADR
# 0014 karar #3'ün "yalnızca arkadaşlar" mirasını taşımaya devam ediyordu —
# sahip cihazda test ederken bunu fark edip düzeltilmesini istedi, ADR 0017
# ile görünürlük de herkese açığa çevrildi. İmleçli sayfalama (created_at,
# id) — service-contract §5. Beğeni/yorum sayısı ve "ben beğendim mi" tek
# sorguda LEFT JOIN + agregasyonla çıkarılıyor.
# ★ LEFT JOIN workout_snapshots ★ (ADR 0016, önceden JOIN idi) — MOTIVATION
# gönderisinin workout_id'si hiç yok, iç JOIN olsaydı o satır feed'den
# tamamen düşerdi. WORKOUT gönderileri için davranış DEĞİŞMEDİ: snapshot her
# zaman var (posts_type_shape_chk zorunlu kılıyor), LEFT JOIN yine tam eşleşir.
_SELECT_FEED = """
SELECT p.id, p.author_id, p.workout_id, p.note, p.created_at, p.post_type,
       (p.photo_content_type IS NOT NULL) AS has_photo,
       s.exercise_id, s.total_sets, s.total_reps, s.reps_with_errors, s.best_set_reps,
       pr.username AS author_username, pr.display_name AS author_display_name,
       pr.avatar_seed AS author_avatar_seed,
       COUNT(DISTINCT l.user_id) AS like_count,
       COUNT(DISTINCT c.id) AS comment_count,
       COALESCE(BOOL_OR(l.user_id = $1), false) AS liked_by_me,
       (sc.post_id IS NOT NULL) AS has_clip
  FROM posts p
  LEFT JOIN workout_snapshots s ON s.workout_id = p.workout_id
  JOIN social_profiles pr ON pr.user_id = p.author_id
  LEFT JOIN post_likes l ON l.post_id = p.id
  LEFT JOIN post_comments c ON c.post_id = p.id
  LEFT JOIN shared_clips sc ON sc.post_id = p.id
 WHERE p.status = 'VISIBLE'
   AND (p.created_at, p.id) < ($2, $3)
 GROUP BY p.id, s.exercise_id, s.total_sets, s.total_reps, s.reps_with_errors,
          s.best_set_reps, pr.username, pr.display_name, pr.avatar_seed, sc.post_id
 ORDER BY p.created_at DESC, p.id DESC
 LIMIT $4
"""

# Tek gönderiyi feed satırıyla AYNI ŞEKİLDE döndürür — motivasyon gönderisi
# oluşturulunca (ya da idempotent tekrar gönderilince) ikinci bir farklı
# alan haritalamasına düşmemek için `app/routers/posts.py` ikisinde de aynı
# `_post_out_from_row` haritalayıcısını kullanıyor.
_SELECT_ONE = """
SELECT p.id, p.author_id, p.workout_id, p.note, p.created_at, p.post_type,
       (p.photo_content_type IS NOT NULL) AS has_photo,
       s.exercise_id, s.total_sets, s.total_reps, s.reps_with_errors, s.best_set_reps,
       pr.username AS author_username, pr.display_name AS author_display_name,
       pr.avatar_seed AS author_avatar_seed,
       COUNT(DISTINCT l.user_id) AS like_count,
       COUNT(DISTINCT c.id) AS comment_count,
       COALESCE(BOOL_OR(l.user_id = $1), false) AS liked_by_me,
       (sc.post_id IS NOT NULL) AS has_clip
  FROM posts p
  LEFT JOIN workout_snapshots s ON s.workout_id = p.workout_id
  JOIN social_profiles pr ON pr.user_id = p.author_id
  LEFT JOIN post_likes l ON l.post_id = p.id
  LEFT JOIN post_comments c ON c.post_id = p.id
  LEFT JOIN shared_clips sc ON sc.post_id = p.id
 WHERE p.id = $2
 GROUP BY p.id, s.exercise_id, s.total_sets, s.total_reps, s.reps_with_errors,
          s.best_set_reps, pr.username, pr.display_name, pr.avatar_seed, sc.post_id
"""

_UPSERT_LIKE = """
INSERT INTO post_likes (post_id, user_id) VALUES ($1, $2)
ON CONFLICT (post_id, user_id) DO NOTHING
"""

_DELETE_LIKE = "DELETE FROM post_likes WHERE post_id = $1 AND user_id = $2"

_INSERT_COMMENT = """
INSERT INTO post_comments (id, post_id, author_id, body, parent_comment_id)
VALUES ($1, $2, $3, $4, $5)
"""

_FIND_COMMENT_BY_ID = """
SELECT id, post_id, author_id, body, created_at, parent_comment_id FROM post_comments WHERE id = $1
"""

# ★ YALNIZCA ÜST SEVİYE ★ (Faz S13 — "yoruma yorum") `parent_comment_id IS
# NULL`: yanıtlar burada değil, `_SELECT_REPLIES`'te. `reply_count` her
# yorumun kaç yanıtı olduğunu tek sorguda taşıyor — istemci "3 yanıt" yazıp
# dokunulunca `_SELECT_REPLIES`'i çağırıyor, her yorum için ayrı bir sayım
# isteği atmıyor.
_SELECT_COMMENTS = """
SELECT c.id, c.post_id, c.author_id, c.body, c.created_at, c.parent_comment_id,
       pr.username, pr.display_name, pr.avatar_seed,
       COUNT(r.id) AS reply_count
  FROM post_comments c
  JOIN social_profiles pr ON pr.user_id = c.author_id
  LEFT JOIN post_comments r ON r.parent_comment_id = c.id
 WHERE c.post_id = $1 AND c.parent_comment_id IS NULL AND (c.created_at, c.id) > ($2, $3)
 GROUP BY c.id, pr.username, pr.display_name, pr.avatar_seed
 ORDER BY c.created_at, c.id
 LIMIT $4
"""

# Bir üst yorumun yanıtları — TEK SEVİYE olduğu için `reply_count` yok,
# sayfalama da yok (bir yorumun yanıtı gerçek kullanımda birkaç düzine
# geçmiyor; geçerse `service-contract` §5 desenine göre eklenir).
_SELECT_REPLIES = """
SELECT c.id, c.post_id, c.author_id, c.body, c.created_at, c.parent_comment_id,
       pr.username, pr.display_name, pr.avatar_seed
  FROM post_comments c
  JOIN social_profiles pr ON pr.user_id = c.author_id
 WHERE c.parent_comment_id = $1
 ORDER BY c.created_at, c.id
 LIMIT 200
"""


@dataclass(frozen=True)
class Post:
    id: uuid.UUID
    author_id: uuid.UUID
    workout_id: uuid.UUID | None
    note: str
    status: str
    created_at: datetime
    post_type: str
    photo_content_type: str | None


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    raw = f"{created_at.timestamp()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID]:
    if cursor is None:
        # En yeni tarihten ileri hiçbir şey yok, sayfalama en baştan başlar.
        return (datetime.now(tz=timezone.utc), uuid.UUID(int=(2**128 - 1)))
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        ts_text, id_text = raw.split("|", 1)
        return (
            datetime.fromtimestamp(float(ts_text), tz=timezone.utc),
            uuid.UUID(id_text),
        )
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise ValueError("geçersiz imleç") from None


async def find_snapshot_owner(conn: asyncpg.Connection, workout_id: uuid.UUID) -> uuid.UUID | None:
    row = await conn.fetchrow(_FIND_SNAPSHOT_OWNER, workout_id)
    return row["user_id"] if row else None


async def create(
    conn: asyncpg.Connection,
    *,
    post_id: uuid.UUID,
    author_id: uuid.UUID,
    workout_id: uuid.UUID | None,
    note: str,
    status: str,
    post_type: str = "WORKOUT",
    photo_content_type: str | None = None,
) -> None:
    await conn.execute(
        _INSERT_POST, post_id, author_id, workout_id, note, status, post_type, photo_content_type
    )


async def find_by_id(conn: asyncpg.Connection, post_id: uuid.UUID) -> Post | None:
    row = await conn.fetchrow(_FIND_POST_BY_ID, post_id)
    return Post(**dict(row)) if row else None


async def fetch_one(conn: asyncpg.Connection, viewer_id: uuid.UUID, post_id: uuid.UUID) -> asyncpg.Record | None:
    """`_SELECT_FEED` ile AYNI alan haritası — motivasyon gönderisi oluşturunca
    `PostOut`'u ikinci bir farklı sorguyla değil, feed'in kullandığı haritalayıcının
    beklediği aynı satır şekliyle döndürmek için."""
    return await conn.fetchrow(_SELECT_ONE, viewer_id, post_id)


async def promote_pending(conn: asyncpg.Connection, workout_id: uuid.UUID, author_id: uuid.UUID) -> bool:
    row = await conn.fetchrow(_PROMOTE_PENDING, workout_id, author_id)
    return row is not None


async def sweep_stale_pending(conn: asyncpg.Connection) -> int:
    rows = await conn.fetch(_DELETE_STALE_PENDING)
    return len(rows)


async def delete(conn: asyncpg.Connection, post_id: uuid.UUID, author_id: uuid.UUID) -> bool:
    row = await conn.fetchrow(_DELETE_POST, post_id, author_id)
    return row is not None


async def find_photo_post_ids_by_author(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Silinmeden ÖNCE çağrılır — MinIO nesnesi Postgres transaction'ının dışında
    olduğu için router burada dönen id listesiyle `storage.delete_photo`'yu
    her biri için ayrı ayrı çağırır (bkz. app/routers/internal.py)."""
    rows = await conn.fetch(_SELECT_PHOTO_POST_IDS_BY_AUTHOR, user_id)
    return [row["id"] for row in rows]


async def delete_all_for_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> None:
    await conn.execute(_DELETE_POSTS_BY_AUTHOR, user_id)
    await conn.execute(_DELETE_LIKES_BY_USER, user_id)
    await conn.execute(_DELETE_COMMENTS_BY_AUTHOR, user_id)


async def fetch_feed(
    conn: asyncpg.Connection,
    viewer_id: uuid.UUID,
    cursor: str | None,
    limit: int,
) -> list[asyncpg.Record]:
    created_at, item_id = decode_cursor(cursor)
    return await conn.fetch(_SELECT_FEED, viewer_id, created_at, item_id, limit)


async def like(conn: asyncpg.Connection, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await conn.execute(_UPSERT_LIKE, post_id, user_id)


async def unlike(conn: asyncpg.Connection, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await conn.execute(_DELETE_LIKE, post_id, user_id)


async def add_comment(
    conn: asyncpg.Connection,
    *,
    comment_id: uuid.UUID,
    post_id: uuid.UUID,
    author_id: uuid.UUID,
    body: str,
    parent_comment_id: uuid.UUID | None = None,
) -> None:
    await conn.execute(_INSERT_COMMENT, comment_id, post_id, author_id, body, parent_comment_id)


async def find_comment_by_id(conn: asyncpg.Connection, comment_id: uuid.UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(_FIND_COMMENT_BY_ID, comment_id)


async def fetch_comments(
    conn: asyncpg.Connection, post_id: uuid.UUID, cursor: str | None, limit: int
) -> list[asyncpg.Record]:
    if cursor is None:
        created_at, item_id = datetime.fromtimestamp(0, tz=timezone.utc), uuid.UUID(int=0)
    else:
        created_at, item_id = decode_cursor(cursor)
    return await conn.fetch(_SELECT_COMMENTS, post_id, created_at, item_id, limit)


async def fetch_replies(conn: asyncpg.Connection, parent_comment_id: uuid.UUID) -> list[asyncpg.Record]:
    return await conn.fetch(_SELECT_REPLIES, parent_comment_id)
