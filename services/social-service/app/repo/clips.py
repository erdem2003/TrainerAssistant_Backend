"""İskelet klibi paylaşımı (ADR 0015, Faz S11) — `social_clips/{post_id}`.

Bu modül landmark verisinin İÇERİĞİNİ hiç yorumlamaz — yalnızca saklayıp
geri verir. Yorumlama (çizim, oynatma) tamamen mobil tarafta.

★ NEDEN SIKIŞTIRILMIŞ JSON (Blob), NEDEN İÇ İÇE ALAN DEĞİL ★
450 kare × 33 landmark × 3 sayı iç içe Firestore alanı olarak (1) doküman
başına 40.000 indeks girdisi sınırını zorlar, (2) ham JSON olarak ~600 KB ile
1 MiB doküman sınırına yaklaşır. zlib'li JSON baytı indekslenmeyen tek bir
Blob alanı; boyut birkaç kat küçülüyor. Postgres'teki JSONB'nin karşılığı:
sunucu içeriği sorgulamıyordu, yalnızca saklıyordu.
"""

from __future__ import annotations

import json
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime

from google.cloud import firestore

from app.db import db


@dataclass(frozen=True)
class SharedClip:
    post_id: uuid.UUID
    landmark_sequence: list
    frame_count: int
    form_errors: list[str]
    image_width: int
    image_height: int
    created_at: datetime


def _ref(post_id: uuid.UUID):
    return db.collection("clips").document(str(post_id))


async def upsert(
    *,
    post_id: uuid.UUID,
    landmark_sequence: list,
    frame_count: int,
    form_errors: list[str],
    image_width: int,
    image_height: int,
) -> bool:
    """Klibi yazar (varsa değiştirir) ve gönderinin `has_clip` bayrağını aynı
    yığında açar; klip daha önce VAR MIYDI döner (201/200 ayrımı için).

    `has_clip` bir sayaç değil, 1:1 ilişkinin varlık bayrağı — Postgres'te feed
    sorgusu `LEFT JOIN shared_clips` ile aynı bilgiyi üretiyordu.
    """
    ref = _ref(post_id)
    existed = (await ref.get()).exists
    blob = zlib.compress(json.dumps(landmark_sequence, separators=(",", ":")).encode("utf-8"))
    batch = db.client.batch()
    batch.set(ref, {
        "landmark_sequence_z": blob,
        "frame_count": frame_count,
        "form_errors": list(form_errors),
        "image_width": image_width,
        "image_height": image_height,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    batch.update(db.collection("posts").document(str(post_id)), {"has_clip": True})
    await batch.commit()
    return existed


async def find_by_post(post_id: uuid.UUID) -> SharedClip | None:
    snap = await _ref(post_id).get()
    if not snap.exists:
        return None
    d = snap.to_dict()
    return SharedClip(
        post_id=post_id,
        landmark_sequence=json.loads(zlib.decompress(d["landmark_sequence_z"]).decode("utf-8")),
        frame_count=int(d["frame_count"]),
        form_errors=list(d.get("form_errors") or []),
        image_width=int(d["image_width"]),
        image_height=int(d["image_height"]),
        created_at=d.get("created_at"),
    )
