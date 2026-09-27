"""shared_clips SQL — iskelet klibi paylaşımı (ADR 0015, Faz S11).

Bu modül landmark verisinin İÇERİĞİNİ hiç yorumlamaz — sunucu tarafında
bir kare bile ayrıştırılmıyor, yalnızca JSONB olarak saklanıp geri veriliyor.
Yorumlama (çizim, oynatma) tamamen mobil tarafta (`ReplayCanvas`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_UPSERT = """
INSERT INTO shared_clips (post_id, landmark_sequence, frame_count, form_errors, image_width, image_height)
VALUES ($1, $2::jsonb, $3, $4, $5, $6)
ON CONFLICT (post_id) DO UPDATE SET
    landmark_sequence = EXCLUDED.landmark_sequence,
    frame_count        = EXCLUDED.frame_count,
    form_errors         = EXCLUDED.form_errors,
    image_width          = EXCLUDED.image_width,
    image_height          = EXCLUDED.image_height,
    created_at              = now()
"""

_FIND_BY_POST = """
SELECT post_id, landmark_sequence, frame_count, form_errors, image_width, image_height, created_at
  FROM shared_clips WHERE post_id = $1
"""

_HAS_CLIP_FOR_POSTS = "SELECT post_id FROM shared_clips WHERE post_id = ANY($1::uuid[])"


@dataclass(frozen=True)
class SharedClip:
    post_id: uuid.UUID
    landmark_sequence: list
    frame_count: int
    form_errors: list[str]
    image_width: int
    image_height: int
    created_at: datetime


async def upsert(
    conn: asyncpg.Connection,
    *,
    post_id: uuid.UUID,
    landmark_sequence: list,
    frame_count: int,
    form_errors: list[str],
    image_width: int,
    image_height: int,
) -> None:
    await conn.execute(
        _UPSERT, post_id, json.dumps(landmark_sequence), frame_count, form_errors, image_width, image_height
    )


async def find_by_post(conn: asyncpg.Connection, post_id: uuid.UUID) -> SharedClip | None:
    row = await conn.fetchrow(_FIND_BY_POST, post_id)
    if row is None:
        return None
    return SharedClip(
        post_id=row["post_id"],
        landmark_sequence=json.loads(row["landmark_sequence"]),
        frame_count=row["frame_count"],
        form_errors=list(row["form_errors"]),
        image_width=row["image_width"],
        image_height=row["image_height"],
        created_at=row["created_at"],
    )


async def posts_with_clips(conn: asyncpg.Connection, post_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Feed sorgusu için: bu gönderilerden hangileri klip taşıyor (has_clip bayrağı)."""
    rows = await conn.fetch(_HAS_CLIP_FOR_POSTS, post_ids)
    return {r["post_id"] for r in rows}
