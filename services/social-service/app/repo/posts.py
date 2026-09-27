"""Gönderi / beğeni / yorum (ADR 0014 Faz S4, 0016, 0017).

★ SAYAÇ YOK ★ Beğeni ve yorum SAYISI hiçbir yerde saklanmıyor — Postgres'teki
`COUNT()`-anında ilkesi korunuyor: Firestore `count()` toplamasıyla okuma anında
sayılıyor (1000 girdiye kadar 1 okuma). Bedeli: feed sayfası başına gönderi
başına ~3 okuma (beğeni sayısı, yorum sayısı, "ben beğendim mi"). Sayaç alanı
okumaları azaltırdı ama "saklanmaz, türetilir" kararını değiştirmek bu portun
kapsamı dışında — açık soru olarak raporlandı.

★ DURUM MAKİNESİ ★ PENDING_SNAPSHOT → VISIBLE aynen duruyor. Durumla birlikte
yalnızca-o-durumda-var alanlar taşınıyor: `pending_since` (süpürücü için),
`feed_at` (feed sıralaması için) — ikisi de tek alanlı indeksle sorgulanıyor
(gerekçe `app/db.py`).

Satır şekli: `fetch_feed`/`fetch_one` Postgres sorgusunun döndürdüğü sütun
adlarının AYNISIYLA sözlük döndürüyor ki router'daki `_post_out_from_row` tek
haritalayıcı olarak kalsın.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from app.db import db
from app.repo import profiles, snapshots

# Snapshot'ı gelmeyen gönderinin ömrü (Postgres'teki `interval '15 minutes'`).
PENDING_TTL = timedelta(minutes=15)


class WorkoutNotFound(Exception):
    """Başkasının workout_id'si — hiç var olmamış gibi davranılır (404)."""


class AlreadyShared(Exception):
    """(author_id, workout_id) UNIQUE — bu antrenman zaten paylaşılmış."""


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
    has_clip: bool = False


def _posts():
    return db.collection("posts")


def _likes():
    return db.collection("post_likes")


def _comments():
    return db.collection("post_comments")


def _lock(author_id: uuid.UUID, workout_id: uuid.UUID):
    return db.collection("workout_posts").document(f"{author_id}_{workout_id}")


def _to_post(snap) -> Post:
    d = snap.to_dict()
    return Post(
        id=uuid.UUID(snap.id),
        author_id=uuid.UUID(d["author_id"]),
        workout_id=uuid.UUID(d["workout_id"]) if d.get("workout_id") else None,
        note=d.get("note", ""),
        status=d["status"],
        created_at=d["created_at"],
        post_type=d.get("post_type", "WORKOUT"),
        photo_content_type=d.get("photo_content_type"),
        has_clip=bool(d.get("has_clip")),
    )


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    raw = f"{created_at.timestamp()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if cursor is None:
        return None
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


# --- Oluşturma -----------------------------------------------------------------


async def find_by_id(post_id: uuid.UUID) -> Post | None:
    snap = await _posts().document(str(post_id)).get()
    return _to_post(snap) if snap.exists else None


async def create_workout_post(
    *, post_id: uuid.UUID, author_id: uuid.UUID, workout_id: uuid.UUID, note: str
) -> tuple[Post | None, str]:
    """(mevcut gönderi | None, durum). Mevcutsa hiçbir şey yazılmaz.

    Tek transaction: idempotency (aynı id), (yazar, antrenman) tekliği,
    sahiplik kontrolü ve hızlı yol (snapshot zaten varsa hemen VISIBLE).
    """
    post_ref = _posts().document(str(post_id))
    lock_ref = _lock(author_id, workout_id)
    now = datetime.now(timezone.utc)

    @firestore.async_transactional
    async def run(tx):
        existing = await post_ref.get(transaction=tx)
        if existing.exists:
            return _to_post(existing), existing.get("status")
        lock = await lock_ref.get(transaction=tx)
        owner_snap = await snapshots.owner_ref(workout_id).get(transaction=tx)
        if lock.exists:
            raise AlreadyShared(str(workout_id))
        owner = uuid.UUID(owner_snap.get("user_id")) if owner_snap.exists else None
        if owner is not None and owner != author_id:
            raise WorkoutNotFound(str(workout_id))
        status = "VISIBLE" if owner == author_id else "PENDING_SNAPSHOT"
        data = {
            "author_id": str(author_id),
            "workout_id": str(workout_id),
            "note": note,
            "status": status,
            "post_type": "WORKOUT",
            "photo_content_type": None,
            "has_clip": False,
            "created_at": now,
        }
        data["feed_at" if status == "VISIBLE" else "pending_since"] = now
        tx.create(post_ref, data)
        tx.create(lock_ref, {"post_id": str(post_id)})
        return None, status

    return await run(db.client.transaction())


async def create_motivation_post(
    *, post_id: uuid.UUID, author_id: uuid.UUID, note: str, photo_content_type: str | None
) -> Post | None:
    """Mevcutsa onu döner (idempotent tekrar); değilse VISIBLE oluşturur ve None."""
    now = datetime.now(timezone.utc)
    try:
        await _posts().document(str(post_id)).create({
            "author_id": str(author_id),
            "workout_id": None,
            "note": note,
            "status": "VISIBLE",
            "post_type": "MOTIVATION",
            "photo_content_type": photo_content_type,
            "has_clip": False,
            "created_at": now,
            "feed_at": now,
        })
        return None
    except AlreadyExists:
        return await find_by_id(post_id)


# --- Terfi / süpürme (tüketici) -------------------------------------------------


async def read_pending_in_tx(tx, workout_id: uuid.UUID, author_id: uuid.UUID):
    """Tüketici transaction'ının OKUMA yarısı: bu (yazar, antrenman) için
    bekleyen gönderi varsa onun snapshot'ı."""
    lock = await _lock(author_id, workout_id).get(transaction=tx)
    if not lock.exists:
        return None
    post = await _posts().document(lock.get("post_id")).get(transaction=tx)
    if not post.exists or post.get("status") != "PENDING_SNAPSHOT":
        return None
    return post


def promote_in_tx(tx, post_snap) -> None:
    """★ TERFİ ★ `author_id` eşleşmesi kilidin kimliğinde zaten var: başkasının
    workout_id'siyle açılmış bir gönderi asla VISIBLE olamaz."""
    tx.update(post_snap.reference, {
        "status": "VISIBLE",
        "feed_at": post_snap.get("created_at"),
        "pending_since": firestore.DELETE_FIELD,
    })


async def sweep_stale_pending() -> int:
    """15 dakikadır PENDING_SNAPSHOT kalan gönderileri siler."""
    cutoff = datetime.now(timezone.utc) - PENDING_TTL
    query = _posts().where(filter=firestore.FieldFilter("pending_since", "<", cutoff)).order_by("pending_since")
    count = 0
    async for snap in query.stream():
        post = _to_post(snap)
        await delete_cascade(post)
        count += 1
    return count


# --- Silme ---------------------------------------------------------------------


async def delete_cascade(post: Post) -> None:
    """Gönderi + beğenileri + yorumları + klibi + kilidi (Postgres'teki
    `ON DELETE CASCADE`). Önce gönderi: görünmez olur; kalan adımlar yarıda
    kalsa bile sahipsiz beğeni/yorum hiçbir okuma yolunda görünmüyor."""
    await _posts().document(str(post.id)).delete()
    for col in (_likes(), _comments()):
        async for snap in col.where(filter=firestore.FieldFilter("post_id", "==", str(post.id))).stream():
            await snap.reference.delete()
    await db.collection("clips").document(str(post.id)).delete()
    if post.workout_id is not None:
        await _lock(post.author_id, post.workout_id).delete()


async def delete(post_id: uuid.UUID, author_id: uuid.UUID) -> Post | None:
    """Yalnızca yazar silebilir; silinen gönderiyi döner (fotoğraf temizliği için)."""
    post = await find_by_id(post_id)
    if post is None or post.author_id != author_id:
        return None
    await delete_cascade(post)
    return post


async def delete_all_for_user(user_id: uuid.UUID) -> list[Post]:
    """Hesap silme: kendi gönderileri (kaskadla), başkalarının gönderisine
    bıraktığı beğeni/yorum ve o yorumlara gelen yanıtlar (Postgres'teki
    `parent_comment_id ... ON DELETE CASCADE`). Silinen gönderileri döner."""
    uid = str(user_id)
    deleted: list[Post] = []
    async for snap in _posts().where(filter=firestore.FieldFilter("author_id", "==", uid)).stream():
        post = _to_post(snap)
        await delete_cascade(post)
        deleted.append(post)
    async for snap in _likes().where(filter=firestore.FieldFilter("user_id", "==", uid)).stream():
        await snap.reference.delete()
    async for snap in _comments().where(filter=firestore.FieldFilter("author_id", "==", uid)).stream():
        replies = _comments().where(filter=firestore.FieldFilter("parent_comment_id", "==", snap.id))
        async for reply in replies.stream():
            await reply.reference.delete()
        await snap.reference.delete()
    return deleted


# --- Okuma: feed ----------------------------------------------------------------


async def _count(query) -> int:
    result = await query.count().get()
    return int(result[0][0].value)


async def _hydrate(viewer_id: uuid.UUID, posts: list[Post]) -> list[dict]:
    """Postgres'teki JOIN'lerin karşılığı: yazar profili (INNER — profili
    olmayan gönderi düşer), snapshot (LEFT), beğeni/yorum sayısı, "ben beğendim".
    Hepsi toplu ya da paralel okunuyor."""
    if not posts:
        return []
    authors = await profiles.profiles_map(p.author_id for p in posts)
    snap_refs = [snapshots.snapshot_ref(p.author_id, p.workout_id) for p in posts if p.workout_id]
    snaps = {}
    if snap_refs:
        async for s in db.client.get_all(snap_refs):
            if s.exists:
                snaps[s.id] = s.to_dict()
    like_refs = [_likes().document(f"{p.id}_{viewer_id}") for p in posts]
    liked = {s.id async for s in db.client.get_all(like_refs) if s.exists}
    like_counts, comment_counts = await asyncio.gather(
        asyncio.gather(*(_count(_likes().where(filter=firestore.FieldFilter("post_id", "==", str(p.id)))) for p in posts)),
        asyncio.gather(*(_count(_comments().where(filter=firestore.FieldFilter("post_id", "==", str(p.id)))) for p in posts)),
    )

    rows = []
    for post, like_count, comment_count in zip(posts, like_counts, comment_counts):
        author = authors.get(post.author_id)
        if author is None:
            continue
        snap = snaps.get(str(post.workout_id)) if post.workout_id else None
        rows.append({
            "id": post.id,
            "author_id": post.author_id,
            "workout_id": post.workout_id,
            "note": post.note,
            "created_at": post.created_at,
            "post_type": post.post_type,
            "has_photo": post.photo_content_type is not None,
            "exercise_id": snap.get("exercise_id") if snap else None,
            "total_sets": snap.get("total_sets") if snap else None,
            "total_reps": snap.get("total_reps") if snap else None,
            "reps_with_errors": snap.get("reps_with_errors") if snap else None,
            "best_set_reps": snap.get("best_set_reps") if snap else None,
            "author_username": author.username,
            "author_display_name": author.display_name,
            "author_avatar_seed": author.avatar_seed,
            "like_count": like_count,
            "comment_count": comment_count,
            "liked_by_me": f"{post.id}_{viewer_id}" in liked,
            "has_clip": post.has_clip,
        })
    return rows


async def fetch_feed(viewer_id: uuid.UUID, cursor: str | None, limit: int) -> list[dict]:
    """★ FEED — HERKESE AÇIK (ADR 0017) ★ Yalnızca VISIBLE (yani `feed_at`
    taşıyan) gönderiler, `(created_at, id)` imleçli, en yeni üstte."""
    query = (
        _posts()
        .order_by("feed_at", direction=firestore.Query.DESCENDING)
        .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
    )
    decoded = decode_cursor(cursor)
    if decoded is not None:
        query = query.start_after({"feed_at": decoded[0], "__name__": str(decoded[1])})
    posts = [_to_post(s) async for s in query.limit(limit).stream()]
    return await _hydrate(viewer_id, posts)


async def fetch_one(viewer_id: uuid.UUID, post_id: uuid.UUID) -> dict | None:
    post = await find_by_id(post_id)
    if post is None:
        return None
    rows = await _hydrate(viewer_id, [post])
    return rows[0] if rows else None


# --- Beğeni ---------------------------------------------------------------------


async def like(post_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """`set()` — ikinci beğeni aynı dokümanı yazar (ON CONFLICT DO NOTHING)."""
    await _likes().document(f"{post_id}_{user_id}").set(
        {"post_id": str(post_id), "user_id": str(user_id), "created_at": firestore.SERVER_TIMESTAMP}
    )


async def unlike(post_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await _likes().document(f"{post_id}_{user_id}").delete()


# --- Yorum ----------------------------------------------------------------------


def _comment_row(snap) -> dict:
    d = snap.to_dict()
    return {
        "id": uuid.UUID(snap.id),
        "post_id": uuid.UUID(d["post_id"]),
        "author_id": uuid.UUID(d["author_id"]),
        "body": d["body"],
        "created_at": d["created_at"],
        "parent_comment_id": uuid.UUID(d["parent_comment_id"]) if d.get("parent_comment_id") else None,
    }


async def add_comment(
    *,
    comment_id: uuid.UUID,
    post_id: uuid.UUID,
    author_id: uuid.UUID,
    body: str,
    parent_comment_id: uuid.UUID | None = None,
) -> dict | None:
    """Yeni yorum oluşturur ve satırını döner; kimlik zaten varsa `None`
    (eşzamanlı idempotent tekrar — çağıran mevcut kaydı okur)."""
    data = {
        "post_id": str(post_id),
        "author_id": str(author_id),
        "body": body,
        "created_at": datetime.now(timezone.utc),
        "parent_comment_id": str(parent_comment_id) if parent_comment_id else None,
    }
    try:
        await _comments().document(str(comment_id)).create(data)
    except AlreadyExists:
        return None
    return {**data, "id": comment_id, "post_id": post_id, "author_id": author_id,
            "parent_comment_id": parent_comment_id}


async def find_comment_by_id(comment_id: uuid.UUID) -> dict | None:
    snap = await _comments().document(str(comment_id)).get()
    return _comment_row(snap) if snap.exists else None


async def _with_authors(rows: list[dict]) -> list[dict]:
    """Yorum yazarı profili — INNER JOIN semantiği (profili olmayan düşer)."""
    authors = await profiles.profiles_map(r["author_id"] for r in rows)
    out = []
    for r in rows:
        author = authors.get(r["author_id"])
        if author is None:
            continue
        out.append({**r, "username": author.username, "display_name": author.display_name,
                    "avatar_seed": author.avatar_seed})
    return out


async def fetch_comments(post_id: uuid.UUID, cursor: str | None, limit: int) -> list[dict]:
    """★ YALNIZCA ÜST SEVİYE ★ + her birinin `reply_count`'u.

    Gönderinin TÜM yorumları tek eşitlik sorgusuyla okunup bellekte
    ayrılıyor: "post_id == X AND parent IS NULL ORDER BY created_at" bileşik
    indeks isterdi. Yanıt sayısı da aynı okumadan, ek sorgu olmadan çıkıyor.
    Okuma: gönderideki yorum sayısı (gerçek kullanımda onlarca).
    """
    after = decode_cursor(cursor) if cursor is not None else None
    query = _comments().where(filter=firestore.FieldFilter("post_id", "==", str(post_id)))
    all_rows = [_comment_row(s) async for s in query.stream()]
    reply_counts: dict[uuid.UUID, int] = {}
    for r in all_rows:
        if r["parent_comment_id"] is not None:
            reply_counts[r["parent_comment_id"]] = reply_counts.get(r["parent_comment_id"], 0) + 1
    top = sorted((r for r in all_rows if r["parent_comment_id"] is None),
                 key=lambda r: (r["created_at"], str(r["id"])))
    if after is not None:
        top = [r for r in top if (r["created_at"], str(r["id"])) > (after[0], str(after[1]))]
    page = [{**r, "reply_count": reply_counts.get(r["id"], 0)} for r in top[:limit]]
    return await _with_authors(page)


async def fetch_replies(parent_comment_id: uuid.UUID) -> list[dict]:
    """Tek seviye, sayfalamasız (en fazla 200) — Postgres'teki `_SELECT_REPLIES`."""
    query = _comments().where(filter=firestore.FieldFilter("parent_comment_id", "==", str(parent_comment_id)))
    rows = sorted([_comment_row(s) async for s in query.stream()], key=lambda r: (r["created_at"], str(r["id"])))
    return await _with_authors(rows[:200])
