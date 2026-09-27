"""Gönderi, feed, beğeni, yorum (ADR 0014, Faz S4).

TEK DOĞRULUK KAYNAĞI: `app/repo/posts.py` — durum makinesi (PENDING_SNAPSHOT ->
VISIBLE) ve sayaçsız (COUNT-at-read) tasarımın gerekçesi orada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, Header, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app import notify, storage
from app.db import db
from app.errors import not_found, unprocessable
from app.identity import require_user_id
from app.ratelimit import comment_create_key, limiter, post_create_key
from app.repo import clips, notifications, posts, profiles
from app.schemas import (
    ClipFrameIn,
    ClipIn,
    ClipOut,
    CommentIn,
    CommentOut,
    CommentPage,
    FeedPage,
    PostAuthorOut,
    PostIn,
    PostOut,
    PostPendingOut,
)

# Sunucu tarafı sınır — ADR 0016 v1 moderasyon kapsamı: yalnızca boyut/format,
# içerik denetimi yok (rapor/şikayet ayrı bir faz).
_MAX_PHOTO_BYTES = 5 * 1024 * 1024
_ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}

router = APIRouter(prefix="/v1/social", tags=["posts"])

_FEED_LIMIT_DEFAULT = 20
_FEED_LIMIT_MAX = 50
_COMMENTS_LIMIT_DEFAULT = 30
_COMMENTS_LIMIT_MAX = 100


def _epoch_ms(dt) -> int:
    return int(dt.timestamp() * 1000)


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise unprocessable(f"'{value}' geçerli bir UUID değil") from None


def _post_out_from_row(r) -> PostOut:
    """`_SELECT_FEED` ve `_SELECT_ONE` AYNI kolon kümesini döndürür — bu tek
    haritalayıcı feed sayfası, tekil gönderi lookup'ı ve motivasyon gönderisi
    oluşturma yanıtı arasında paylaşılıyor. İki ayrı haritalayıcı yazmak,
    ADR 0016 sonrası ikisinin sessizce ayrışması demekti."""
    return PostOut(
        id=str(r["id"]),
        author=PostAuthorOut(
            user_id=str(r["author_id"]),
            username=r["author_username"],
            display_name=r["author_display_name"],
            avatar_seed=r["author_avatar_seed"],
        ),
        post_type=r["post_type"],
        workout_id=str(r["workout_id"]) if r["workout_id"] is not None else None,
        note=r["note"],
        exercise_id=r["exercise_id"],
        total_sets=r["total_sets"],
        total_reps=r["total_reps"],
        reps_with_errors=r["reps_with_errors"],
        best_set_reps=r["best_set_reps"],
        has_photo=r["has_photo"],
        like_count=r["like_count"],
        comment_count=r["comment_count"],
        liked_by_me=r["liked_by_me"],
        has_clip=r["has_clip"],
        created_at=_epoch_ms(r["created_at"]),
    )


def _comment_out_from_row(r) -> CommentOut:
    """`_SELECT_COMMENTS` (üst seviye, `reply_count` dolu) ve `_SELECT_REPLIES`
    (yanıt, `reply_count` sütunu YOK) arasında paylaşılan haritalayıcı —
    `dict(r).get(...)` ikinci sorgunun eksik sütununda KeyError yerine 0 verir."""
    row = dict(r)
    return CommentOut(
        id=str(row["id"]),
        post_id=str(row["post_id"]),
        author=PostAuthorOut(
            user_id=str(row["author_id"]),
            username=row["username"],
            display_name=row["display_name"],
            avatar_seed=row["avatar_seed"],
        ),
        body=row["body"],
        parent_comment_id=str(row["parent_comment_id"]) if row["parent_comment_id"] else None,
        reply_count=row.get("reply_count", 0),
        created_at=_epoch_ms(row["created_at"]),
    )


async def _require_post_visible_to(conn, post_id: uuid.UUID, viewer_id: uuid.UUID) -> posts.Post:
    """Gönderiyi getirir; VISIBLE değilse 404 (service-contract §3).

    ADR 0017 — feed herkese açık: burada artık arkadaşlık kontrolü YOK, her
    kimliği doğrulanmış kullanıcı VISIBLE her gönderiyi (beğeni/yorum/foto/klip
    dahil) görebilir. `viewer_id` parametresi yine de duruyor — çağıran
    taraflar (`like_post`, `add_comment`) "kendi gönderime bildirim gitmesin"
    kararını hâlâ `post.author_id != viewer_id` ile veriyor."""
    post = await posts.find_by_id(conn, post_id)
    if post is None or post.status != "VISIBLE":
        raise not_found("Gönderi bulunamadı")
    return post


# --- Gönderi oluşturma / silme ------------------------------------------------


@router.post("/posts", response_model=PostPendingOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    body: PostIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> PostPendingOut:
    """Antrenmanı paylaşır. AYNI id İKİNCİ KEZ GELİRSE yeni kayıt açılmaz
    (service-contract §4, 201/200 merdiveni — çakışma senaryosu burada
    anlamsız: aynı id farklı workout_id ile gelemez, çünkü istemci id'yi
    workout_id'den türetiyor; farklı gelirse 409 yerine yeni kayıt reddedilir
    çünkü doğal anahtar zaten `posts_author_workout_idx` ile korunuyor)."""
    author_id = require_user_id(x_user_id)
    # 30 paylaşım / saat — gerçek kullanımda bir günde birkaç antrenman
    # paylaşılır, bu sınıra asla yaklaşmaz.
    await limiter.hit(post_create_key(author_id), limit=30, window_seconds=3600)

    post_id = _parse_uuid(body.id)
    workout_id = _parse_uuid(body.workout_id)

    async with db.pool.acquire() as conn:
        existing = await posts.find_by_id(conn, post_id)
        if existing is not None:
            if existing.author_id != author_id:
                raise not_found("Gönderi bulunamadı")
            response.status_code = status.HTTP_200_OK
            return PostPendingOut(id=str(existing.id), status=existing.status)

        # Sosyali hiç açmamış (kullanıcı adı almamış) biri paylaşım
        # oluşturamaz — açtıysa bile profil satırı `social_profiles`'ta
        # olmalı, yoksa gönderi feed sorgusundaki JOIN'de asla eşleşmez ve
        # sonsuza kadar görünmez kalır (app/repo/posts.py _SELECT_FEED).
        author_profile = await profiles.find_by_user_id(conn, author_id)
        if author_profile is None or not author_profile.social_enabled:
            raise unprocessable("Paylaşım yapmadan önce sosyali açmalısın")

        # ★ HIZLI YOL ★ Snapshot zaten varsa (Faz S3 tüketicisi antrenmanı
        # önceden işlemişse) ve yazara aitse, hemen VISIBLE — kullanıcı
        # "paylaş"a bastığında feed'de göremezse kafası karışır.
        snapshot_owner = await posts.find_snapshot_owner(conn, workout_id)
        if snapshot_owner is not None and snapshot_owner != author_id:
            # Başkasının workout_id'si — asla var olmamış gibi davran.
            raise not_found("Antrenman bulunamadı")

        initial_status = "VISIBLE" if snapshot_owner == author_id else "PENDING_SNAPSHOT"
        try:
            await posts.create(
                conn,
                post_id=post_id,
                author_id=author_id,
                workout_id=workout_id,
                note=body.note,
                status=initial_status,
            )
        except Exception as exc:
            # UNIQUE (author_id, workout_id) ihlali: bu antrenman zaten
            # paylaşılmış — ayrıntı sızdırmadan aynı sonucu döndür.
            if "posts_author_workout_idx" in str(exc):
                raise unprocessable("Bu antrenman zaten paylaşılmış") from None
            raise

    return PostPendingOut(id=str(post_id), status=initial_status)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: str, x_user_id: str | None = Header(default=None)) -> None:
    author_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    async with db.pool.acquire() as conn:
        existing = await posts.find_by_id(conn, pid)
        deleted = await posts.delete(conn, pid, author_id)

    if not deleted:
        raise not_found("Gönderi bulunamadı")

    if existing is not None and existing.photo_content_type is not None:
        await run_in_threadpool(storage.delete_photo, post_id)


# --- Feed ----------------------------------------------------------------


@router.get("/feed", response_model=FeedPage)
async def get_feed(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=_FEED_LIMIT_DEFAULT, le=_FEED_LIMIT_MAX),
    x_user_id: str | None = Header(default=None),
) -> FeedPage:
    viewer_id = require_user_id(x_user_id)

    try:
        posts.decode_cursor(cursor)
    except ValueError:
        raise unprocessable("Sayfalama imleci geçersiz") from None

    async with db.pool.acquire() as conn:
        # ADR 0017 — feed herkese açık: arkadaş listesi artık FİLTRE değil,
        # yalnızca `_post_out_from_row`'un `liked_by_me` hesabı için `viewer_id`
        # kullanılıyor. +1 ile "sonraki sayfa var mı" ekstra sorgu olmadan çıkar.
        rows = await posts.fetch_feed(conn, viewer_id, cursor, limit + 1)

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [_post_out_from_row(r) for r in rows]

    next_cursor = posts.encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if has_more and rows else None
    return FeedPage(items=items, next_cursor=next_cursor)


# --- Motivasyon gönderisi (ADR 0016, Faz S12) --------------------------------


@router.post("/posts/motivation", response_model=PostOut, status_code=status.HTTP_201_CREATED)
async def create_motivation_post(
    response: Response,
    id: str = Form(),
    note: str = Form(default=""),
    photo: UploadFile | None = None,
    x_user_id: str | None = Header(default=None),
) -> PostOut:
    """Antrenmana bağlı olmayan serbest gönderi — metin ve/veya fotoğraf.

    İdempotent yazım merdiveni WORKOUT gönderisiyle AYNI (service-contract
    §4): aynı `id` ikinci kez gelirse 200 + mevcut kayıt, gövde farklıysa
    (bu v1'de fotoğraf gövdesini karşılaştırmak pahalı olduğundan) basitçe
    var olan kaydı döndürüyoruz — tekrar deneme senaryosu zaten aynı isteği
    aynen tekrarlar.
    """
    author_id = require_user_id(x_user_id)
    await limiter.hit(post_create_key(author_id), limit=30, window_seconds=3600)

    post_id = _parse_uuid(id)
    note = note.strip()

    photo_bytes: bytes | None = None
    photo_content_type: str | None = None
    if photo is not None and photo.filename:
        if photo.content_type not in _ALLOWED_PHOTO_TYPES:
            raise unprocessable(
                f"Desteklenmeyen fotoğraf formatı: {photo.content_type}",
                {"allowed": sorted(_ALLOWED_PHOTO_TYPES)},
            )
        photo_bytes = await photo.read()
        if len(photo_bytes) > _MAX_PHOTO_BYTES:
            raise unprocessable(
                "Fotoğraf çok büyük (en fazla 5 MB)", {"max_bytes": _MAX_PHOTO_BYTES}
            )
        photo_content_type = photo.content_type

    if not note and photo_bytes is None:
        raise unprocessable("Boş gönderi paylaşılamaz — metin ya da fotoğraf gerekli")

    async with db.pool.acquire() as conn:
        existing = await posts.find_by_id(conn, post_id)
        if existing is not None:
            if existing.author_id != author_id:
                raise not_found("Gönderi bulunamadı")
            response.status_code = status.HTTP_200_OK
            row = await posts.fetch_one(conn, author_id, post_id)
            return _post_out_from_row(row)

        author_profile = await profiles.find_by_user_id(conn, author_id)
        if author_profile is None or not author_profile.social_enabled:
            raise unprocessable("Paylaşım yapmadan önce sosyali açmalısın")

        await posts.create(
            conn,
            post_id=post_id,
            author_id=author_id,
            workout_id=None,
            note=note,
            status="VISIBLE",
            post_type="MOTIVATION",
            photo_content_type=photo_content_type,
        )

        if photo_bytes is not None:
            # MinIO yazımı Postgres transaction'ının DIŞINDA — `conn.transaction()`
            # kullanılmıyor zaten (bu router'daki diğer INSERT'lerle aynı desen,
            # `db.pool.acquire()` tek başına transaction açmaz). Satır zaten
            # yazıldıktan sonra fotoğraf konur: nadir bir yarış durumunda (INSERT
            # başarılı, MinIO yazımı çöker) `has_photo` görünse de fotoğraf ucu
            # 404 döner — bu, tersinden (fotoğraf var, satır yok) daha güvenli.
            await run_in_threadpool(storage.put_photo, str(post_id), photo_bytes, photo_content_type)

        row = await posts.fetch_one(conn, author_id, post_id)

    return _post_out_from_row(row)


@router.get("/posts/{post_id}/photo")
async def get_post_photo(post_id: str, x_user_id: str | None = Header(default=None)) -> StreamingResponse:
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    async with db.pool.acquire() as conn:
        await _require_post_visible_to(conn, pid, viewer_id)

    result = await run_in_threadpool(storage.get_photo, str(pid))
    if result is None:
        raise not_found("Fotoğraf bulunamadı")
    data, content_type = result
    return StreamingResponse(iter([data]), media_type=content_type)


# --- Beğeni ----------------------------------------------------------------


@router.post("/posts/{post_id}/likes", status_code=status.HTTP_204_NO_CONTENT)
async def like_post(post_id: str, x_user_id: str | None = Header(default=None)) -> None:
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    upserted = None
    async with db.pool.acquire() as conn:
        post = await _require_post_visible_to(conn, pid, viewer_id)
        await posts.like(conn, pid, viewer_id)

        # Kendi gönderini beğenmek bildirim ÜRETMEZ — kimseye bir şey
        # bildirmiyor, kendine mesaj atmanın anlamsızlığıyla aynı.
        if post.author_id != viewer_id:
            upserted = await notifications.upsert(
                conn,
                notification_id=uuid.uuid4(),
                recipient_id=post.author_id,
                notification_type="POST_LIKED",
                actor_id=viewer_id,
                subject_id=pid,
            )

    if upserted is not None:
        await notify.publish_notification(
            post.author_id,
            notification_id=upserted.id,
            notification_type="POST_LIKED",
            actor_id=viewer_id,
            subject_id=pid,
            created_at_ms=int(upserted.created_at.timestamp() * 1000),
        )


@router.delete("/posts/{post_id}/likes", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_post(post_id: str, x_user_id: str | None = Header(default=None)) -> None:
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    async with db.pool.acquire() as conn:
        await posts.unlike(conn, pid, viewer_id)


# --- Yorum -------------------------------------------------------------------


@router.post("/posts/{post_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(
    post_id: str,
    body: CommentIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> CommentOut:
    author_id = require_user_id(x_user_id)
    # 60 yorum / saat — gerçek sohbet temposunun çok üzerinde, spam sınırı.
    await limiter.hit(comment_create_key(author_id), limit=60, window_seconds=3600)

    pid = _parse_uuid(post_id)
    comment_id = _parse_uuid(body.id)
    parent_id = _parse_uuid(body.parent_comment_id) if body.parent_comment_id else None

    upserted_notification = None
    async with db.pool.acquire() as conn:
        post = await _require_post_visible_to(conn, pid, author_id)

        # `_require_post_visible_to` yazarın kendisi ya da arkadaşı olmayı
        # şart koşuyor ama profil VARLIĞINI koşmuyor — yorum yanıtı yazarın
        # ad/kullanıcı adını taşıdığı için burada da gerekli (aksi halde
        # aşağıdaki fetchrow None döner ve subscript çöker).
        author_profile = await profiles.find_by_user_id(conn, author_id)
        if author_profile is None or not author_profile.social_enabled:
            raise unprocessable("Yorum yapmadan önce sosyali açmalısın")

        # ★ TEK SEVİYE ZORUNLULUĞU ★ (Faz S13) — `parent_id` verilmişse AYNI
        # gönderiye ait ve KENDİSİ bir yanıt OLMAMALI (yanıtın yanıtı yok,
        # migration 008'in yorumu). İkisi de sağlanmazsa 404: var olmayan bir
        # kaynağa yanıt yazmaya çalışmakla aynı sınıf hata.
        if parent_id is not None:
            parent = await posts.find_comment_by_id(conn, parent_id)
            if parent is None or parent["post_id"] != pid or parent["parent_comment_id"] is not None:
                raise not_found("Yanıt verilecek yorum bulunamadı")

        existing = await posts.find_comment_by_id(conn, comment_id)
        if existing is not None:
            if existing["author_id"] != author_id or existing["post_id"] != pid:
                raise not_found("Yorum bulunamadı")
            response.status_code = status.HTTP_200_OK
            body_text, created_at, existing_parent = (
                existing["body"], existing["created_at"], existing["parent_comment_id"]
            )
        else:
            await posts.add_comment(
                conn, comment_id=comment_id, post_id=pid, author_id=author_id,
                body=body.body, parent_comment_id=parent_id,
            )
            row = await posts.find_comment_by_id(conn, comment_id)
            body_text, created_at, existing_parent = row["body"], row["created_at"], row["parent_comment_id"]

            # Yalnızca GERÇEKTEN yeni bir yorumda bildirim üretilir — idempotent
            # tekrar (aynı id, aynı gövde, ağ hatası sonrası retry) ikinci bir
            # bildirim YARATMAMALI. Kendi gönderine yorum da bildirim üretmez.
            #
            # Yanıtta bildirim ALICISI gönderi yazarı değil ÜST YORUMUN yazarı
            # olmalı (Twitter'ın "birisi yanıtınıza cevap verdi" davranışı) —
            # ama bu ADR/spec dışı bir kapsam genişlemesi olurdu, v1'de bildirim
            # hâlâ gönderi yazarına gidiyor (üst yorum yazarı zaten çoğu zaman
            # gönderiyi de takip ediyor olacak, ayrı bir bildirim türü şimdilik
            # gereksiz karmaşıklık).
            if post.author_id != author_id:
                upserted_notification = await notifications.upsert(
                    conn,
                    notification_id=uuid.uuid4(),
                    recipient_id=post.author_id,
                    notification_type="POST_COMMENTED",
                    actor_id=author_id,
                    subject_id=pid,
                )

    if upserted_notification is not None:
        await notify.publish_notification(
            post.author_id,
            notification_id=upserted_notification.id,
            notification_type="POST_COMMENTED",
            actor_id=author_id,
            subject_id=pid,
            created_at_ms=int(upserted_notification.created_at.timestamp() * 1000),
        )

    return CommentOut(
        id=str(comment_id),
        post_id=str(pid),
        author=PostAuthorOut(
            user_id=str(author_id),
            username=author_profile.username,
            display_name=author_profile.display_name,
            avatar_seed=author_profile.avatar_seed,
        ),
        body=body_text,
        parent_comment_id=str(existing_parent) if existing_parent else None,
        created_at=_epoch_ms(created_at),
    )


@router.get("/posts/{post_id}/comments", response_model=CommentPage)
async def list_comments(
    post_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=_COMMENTS_LIMIT_DEFAULT, le=_COMMENTS_LIMIT_MAX),
    x_user_id: str | None = Header(default=None),
) -> CommentPage:
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    if cursor is not None:
        try:
            posts.decode_cursor(cursor)
        except ValueError:
            raise unprocessable("Sayfalama imleci geçersiz") from None

    async with db.pool.acquire() as conn:
        await _require_post_visible_to(conn, pid, viewer_id)
        rows = await posts.fetch_comments(conn, pid, cursor, limit + 1)

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [_comment_out_from_row(r) for r in rows]

    next_cursor = posts.encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if has_more and rows else None
    return CommentPage(items=items, next_cursor=next_cursor)


@router.get("/posts/{post_id}/comments/{comment_id}/replies", response_model=list[CommentOut])
async def list_replies(
    post_id: str,
    comment_id: str,
    x_user_id: str | None = Header(default=None),
) -> list[CommentOut]:
    """Faz S13, "yoruma yorum" — bir üst yorumun TÜM yanıtları, sayfalamasız
    (bkz. `_SELECT_REPLIES`'in gerekçesi: tek seviye, gerçek kullanımda az)."""
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)
    cid = _parse_uuid(comment_id)

    async with db.pool.acquire() as conn:
        await _require_post_visible_to(conn, pid, viewer_id)
        parent = await posts.find_comment_by_id(conn, cid)
        if parent is None or parent["post_id"] != pid:
            raise not_found("Yorum bulunamadı")
        rows = await posts.fetch_replies(conn, cid)

    return [_comment_out_from_row(r) for r in rows]


# --- İskelet klibi paylaşımı (ADR 0015, Faz S11) -------------------------------


@router.post("/posts/{post_id}/clip", response_model=ClipOut, status_code=status.HTTP_201_CREATED)
async def upload_clip(
    post_id: str,
    body: ClipIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> ClipOut:
    """Yalnızca gönderinin YAZARI klip ekleyebilir/değiştirebilir — ADR 0015'in
    "elle seçim" kararı: kullanıcı kendi antrenmanından tek bir tekrarı işaretler."""
    author_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    async with db.pool.acquire() as conn:
        post = await posts.find_by_id(conn, pid)
        if post is None or post.author_id != author_id:
            raise not_found("Gönderi bulunamadı")

        existing = await clips.find_by_post(conn, pid)

        await clips.upsert(
            conn,
            post_id=pid,
            landmark_sequence=[f.model_dump() for f in body.frames],
            frame_count=len(body.frames),
            form_errors=body.form_errors,
            image_width=body.image_width,
            image_height=body.image_height,
        )

    response.status_code = status.HTTP_200_OK if existing is not None else status.HTTP_201_CREATED
    return ClipOut(
        post_id=str(pid),
        frames=body.frames,
        form_errors=body.form_errors,
        frame_count=len(body.frames),
        image_width=body.image_width,
        image_height=body.image_height,
    )


@router.get("/posts/{post_id}/clip", response_model=ClipOut)
async def get_clip(post_id: str, x_user_id: str | None = Header(default=None)) -> ClipOut:
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    async with db.pool.acquire() as conn:
        await _require_post_visible_to(conn, pid, viewer_id)
        clip = await clips.find_by_post(conn, pid)

    if clip is None:
        raise not_found("Klip bulunamadı")

    return ClipOut(
        post_id=str(clip.post_id),
        frames=[ClipFrameIn(**f) for f in clip.landmark_sequence],
        form_errors=clip.form_errors,
        frame_count=clip.frame_count,
        image_width=clip.image_width,
        image_height=clip.image_height,
    )
