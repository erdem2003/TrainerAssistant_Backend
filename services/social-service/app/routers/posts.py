"""Gönderi, feed, beğeni, yorum (ADR 0014, Faz S4).

TEK DOĞRULUK KAYNAĞI: `app/repo/posts.py` — durum makinesi (PENDING_SNAPSHOT ->
VISIBLE) ve sayaçsız (count-at-read) tasarımın gerekçesi orada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, Header, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app import storage
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
    """Feed sayfası, tekil gönderi ve motivasyon gönderisi yanıtı arasında
    paylaşılan TEK haritalayıcı — `repo/posts._hydrate` aynı alan adlarını
    üretiyor. İki ayrı haritalayıcı, ADR 0016 sonrası sessiz ayrışma demekti."""
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


def _comment_out_from_row(row: dict) -> CommentOut:
    """Üst seviye (`reply_count` dolu) ve yanıt (`reply_count` yok) arasında
    paylaşılan haritalayıcı."""
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


async def _require_post_visible_to(post_id: uuid.UUID, viewer_id: uuid.UUID) -> posts.Post:
    """Gönderiyi getirir; VISIBLE değilse 404 (service-contract §3).

    ADR 0017 — feed herkese açık: arkadaşlık kontrolü YOK. `viewer_id`
    duruyor: çağıranlar "kendi gönderime bildirim gitmesin" kararını
    `post.author_id != viewer_id` ile veriyor."""
    post = await posts.find_by_id(post_id)
    if post is None or post.status != "VISIBLE":
        raise not_found("Gönderi bulunamadı")
    return post


async def _require_social_enabled(user_id: uuid.UUID, message: str) -> profiles.SocialProfile:
    profile = await profiles.find_by_user_id(user_id)
    if profile is None or not profile.social_enabled:
        raise unprocessable(message)
    return profile


# --- Gönderi oluşturma / silme ------------------------------------------------


@router.post("/posts", response_model=PostPendingOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    body: PostIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> PostPendingOut:
    """Antrenmanı paylaşır. AYNI id İKİNCİ KEZ GELİRSE yeni kayıt açılmaz
    (service-contract §4, 201/200 merdiveni). Aynı antrenmanı farklı bir
    gönderi kimliğiyle ikinci kez paylaşmak 422 — (yazar, antrenman) tekliği
    `social_workout_posts` kilidinde."""
    author_id = require_user_id(x_user_id)
    # 30 paylaşım / saat — gerçek kullanımda bir günde birkaç antrenman
    # paylaşılır, bu sınıra asla yaklaşmaz.
    await limiter.hit(post_create_key(author_id), limit=30, window_seconds=3600)

    post_id = _parse_uuid(body.id)
    workout_id = _parse_uuid(body.workout_id)

    # Sosyali hiç açmamış biri paylaşım oluşturamaz — profil olmadan gönderi
    # feed'de yazar bilgisiyle eşleşmez ve sonsuza kadar görünmez kalırdı.
    existing = await posts.find_by_id(post_id)
    if existing is None:
        await _require_social_enabled(author_id, "Paylaşım yapmadan önce sosyali açmalısın")

    try:
        existing, initial_status = await posts.create_workout_post(
            post_id=post_id, author_id=author_id, workout_id=workout_id, note=body.note
        )
    except posts.WorkoutNotFound:
        # Başkasının workout_id'si — asla var olmamış gibi davran.
        raise not_found("Antrenman bulunamadı") from None
    except posts.AlreadyShared:
        raise unprocessable("Bu antrenman zaten paylaşılmış") from None

    if existing is not None:
        if existing.author_id != author_id:
            raise not_found("Gönderi bulunamadı")
        response.status_code = status.HTTP_200_OK
        return PostPendingOut(id=str(existing.id), status=existing.status)

    return PostPendingOut(id=str(post_id), status=initial_status)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: str, x_user_id: str | None = Header(default=None)) -> None:
    author_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    deleted = await posts.delete(pid, author_id)
    if deleted is None:
        raise not_found("Gönderi bulunamadı")

    if deleted.photo_content_type is not None:
        await run_in_threadpool(storage.delete_photo, str(pid))


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

    # ADR 0017 — feed herkese açık; `viewer_id` yalnızca `liked_by_me` için.
    # +1 ile "sonraki sayfa var mı" ekstra sorgu olmadan çıkar.
    rows = await posts.fetch_feed(viewer_id, cursor, limit + 1)

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

    İdempotent yazım merdiveni WORKOUT gönderisiyle AYNI (service-contract §4):
    aynı `id` ikinci kez gelirse 200 + mevcut kayıt.
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

    existing = await posts.find_by_id(post_id)
    if existing is None:
        await _require_social_enabled(author_id, "Paylaşım yapmadan önce sosyali açmalısın")
        existing = await posts.create_motivation_post(
            post_id=post_id, author_id=author_id, note=note, photo_content_type=photo_content_type
        )
        if existing is None and photo_bytes is not None:
            # Storage yazımı Firestore yazımının DIŞINDA ve SONRASINDA: nadir bir
            # yarışta (doküman yazıldı, yükleme çöktü) `has_photo` görünse de
            # fotoğraf ucu 404 döner — tersinden (fotoğraf var, gönderi yok)
            # daha güvenli. MinIO dalındaki sıranın aynısı.
            await run_in_threadpool(storage.put_photo, str(post_id), photo_bytes, photo_content_type)

    if existing is not None:
        if existing.author_id != author_id:
            raise not_found("Gönderi bulunamadı")
        response.status_code = status.HTTP_200_OK

    row = await posts.fetch_one(author_id, post_id)
    return _post_out_from_row(row)


@router.get("/posts/{post_id}/photo")
async def get_post_photo(post_id: str, x_user_id: str | None = Header(default=None)) -> StreamingResponse:
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    await _require_post_visible_to(pid, viewer_id)

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

    post = await _require_post_visible_to(pid, viewer_id)
    await posts.like(pid, viewer_id)

    # Kendi gönderini beğenmek bildirim ÜRETMEZ.
    if post.author_id != viewer_id:
        await notifications.upsert(
            recipient_id=post.author_id,
            notification_type="POST_LIKED",
            actor_id=viewer_id,
            subject_id=pid,
        )


@router.delete("/posts/{post_id}/likes", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_post(post_id: str, x_user_id: str | None = Header(default=None)) -> None:
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    await posts.unlike(pid, viewer_id)


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

    post = await _require_post_visible_to(pid, author_id)

    # Yorum yanıtı yazarın ad/kullanıcı adını taşıdığı için profil gerekli.
    author_profile = await _require_social_enabled(author_id, "Yorum yapmadan önce sosyali açmalısın")

    # ★ TEK SEVİYE ZORUNLULUĞU ★ (Faz S13) — üst yorum AYNI gönderiye ait ve
    # KENDİSİ bir yanıt OLMAMALI (yanıtın yanıtı yok). Değilse 404.
    if parent_id is not None:
        parent = await posts.find_comment_by_id(parent_id)
        if parent is None or parent["post_id"] != pid or parent["parent_comment_id"] is not None:
            raise not_found("Yanıt verilecek yorum bulunamadı")

    existing = await posts.find_comment_by_id(comment_id)
    created = None
    if existing is None:
        created = await posts.add_comment(
            comment_id=comment_id, post_id=pid, author_id=author_id,
            body=body.body, parent_comment_id=parent_id,
        )
        if created is None:
            # Eşzamanlı idempotent tekrar yarışı kaybetti — mevcut kaydı oku.
            existing = await posts.find_comment_by_id(comment_id)

    if created is None:
        if existing["author_id"] != author_id or existing["post_id"] != pid:
            raise not_found("Yorum bulunamadı")
        response.status_code = status.HTTP_200_OK
        row = existing
    else:
        row = created
        # Yalnızca GERÇEKTEN yeni bir yorumda bildirim üretilir — idempotent
        # tekrar ikinci bir bildirim YARATMAMALI. Kendi gönderine yorum da
        # bildirim üretmez. Yanıtta alıcı v1'de hâlâ gönderi yazarı.
        if post.author_id != author_id:
            await notifications.upsert(
                recipient_id=post.author_id,
                notification_type="POST_COMMENTED",
                actor_id=author_id,
                subject_id=pid,
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
        body=row["body"],
        parent_comment_id=str(row["parent_comment_id"]) if row["parent_comment_id"] else None,
        created_at=_epoch_ms(row["created_at"]),
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

    await _require_post_visible_to(pid, viewer_id)
    rows = await posts.fetch_comments(pid, cursor, limit + 1)

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
    """Faz S13, "yoruma yorum" — bir üst yorumun TÜM yanıtları, sayfalamasız."""
    viewer_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)
    cid = _parse_uuid(comment_id)

    await _require_post_visible_to(pid, viewer_id)
    parent = await posts.find_comment_by_id(cid)
    if parent is None or parent["post_id"] != pid:
        raise not_found("Yorum bulunamadı")
    rows = await posts.fetch_replies(cid)

    return [_comment_out_from_row(r) for r in rows]


# --- İskelet klibi paylaşımı (ADR 0015, Faz S11) -------------------------------


@router.post("/posts/{post_id}/clip", response_model=ClipOut, status_code=status.HTTP_201_CREATED)
async def upload_clip(
    post_id: str,
    body: ClipIn,
    response: Response,
    x_user_id: str | None = Header(default=None),
) -> ClipOut:
    """Yalnızca gönderinin YAZARI klip ekleyebilir/değiştirebilir (ADR 0015)."""
    author_id = require_user_id(x_user_id)
    pid = _parse_uuid(post_id)

    post = await posts.find_by_id(pid)
    if post is None or post.author_id != author_id:
        raise not_found("Gönderi bulunamadı")

    existed = await clips.upsert(
        post_id=pid,
        landmark_sequence=[f.model_dump() for f in body.frames],
        frame_count=len(body.frames),
        form_errors=body.form_errors,
        image_width=body.image_width,
        image_height=body.image_height,
    )

    response.status_code = status.HTTP_200_OK if existed else status.HTTP_201_CREATED
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

    await _require_post_visible_to(pid, viewer_id)
    clip = await clips.find_by_post(pid)

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
