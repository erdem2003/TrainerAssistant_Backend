"""DELETE /internal/users/{id} — hesap silindiginde sosyal veriyi temizler.
Gateway bu yolu yayinlamaz; yalnizca compose agi icinden cagrilir.

`workout-service/app/routers/internal.py`'nin deseni, ama silme kapsami
daha genis: profil, arkadaslik (her iki tarafta), ve bir TOMBSTONE
(`deleted_users`) — S3'te eklenecek `workout.session` tuketicisinin gecikmeli
gelen bir event icin satiri DIRILTMEMESI icin (ADR 0014, Sonuclar).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Query, Response, status
from starlette.concurrency import run_in_threadpool

from app import storage
from app.config import settings
from app.db import db
from app.errors import ApiError, forbidden, unprocessable
from app.repo import challenges, friendships, notifications, posts, processed_events, profiles, snapshots

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

EVENT_ACCOUNT_DELETED = "AccountDeleted"

_INSERT_TOMBSTONE = "INSERT INTO deleted_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING"


def _require_internal_key(provided: str | None) -> None:
    if not settings.internal_api_key:
        logger.error("INTERNAL_API_KEY tanımsız — /internal uçları kapalı")
        raise forbidden()
    if provided != settings.internal_api_key:
        logger.warning("geçersiz internal anahtarı ile /internal çağrısı")
        raise forbidden()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_data(
    user_id: uuid.UUID,
    x_internal_key: str | None = Header(default=None),
    x_event_id: str | None = Header(default=None),
) -> Response:
    _require_internal_key(x_internal_key)

    if not x_event_id:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "X-Event-Id başlığı zorunlu"
        )

    try:
        event_id = uuid.UUID(x_event_id)
    except ValueError:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "X-Event-Id geçerli bir UUID olmalı"
        ) from None

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            first_time = await processed_events.claim(conn, event_id, EVENT_ACCOUNT_DELETED)
            if not first_time:
                logger.info("event zaten işlenmiş, atlanıyor event_id=%s", event_id)
                return Response(status_code=status.HTTP_204_NO_CONTENT)

            deleted_friendships = await friendships.delete_all_for_user(conn, user_id)
            await profiles.delete_and_retire(conn, user_id)
            deleted_snapshots = await snapshots.delete_by_user(conn, user_id)
            # ADR 0016 — MinIO nesnesi Postgres transaction'ının dışında; satır
            # silinmeden ÖNCE hangi gönderilerin fotoğrafı olduğu okunuyor,
            # transaction commit olduktan SONRA (fonksiyonun sonunda) MinIO'dan
            # siliniyor. Sıra tersine çevrilseydi (önce MinIO, sonra DB) ve
            # transaction rollback olsaydı fotoğraf kalıcı kaybolurdu.
            photo_post_ids = await posts.find_photo_post_ids_by_author(conn, user_id)
            # Kendi gönderileri (CASCADE ile kendi beğeni/yorumları da gider)
            # + başkalarının gönderilerine bıraktığı beğeni/yorum.
            await posts.delete_all_for_user(conn, user_id)
            # Yalnızca KENDİ gelen kutusu silinir — bu kullanıcının bir
            # başkasına AKTÖR olarak bıraktığı bildirimler (S10'a kadar)
            # `NotificationActorOut`'un tüm alanları opsiyonel olduğu için
            # "Silinmiş kullanıcı" olarak LEFT JOIN ile zaten güvenle gösteriliyor.
            await notifications.delete_by_recipient(conn, user_id)
            await challenges.delete_for_user(conn, user_id)
            await challenges.delete_kudos_by_giver(conn, user_id)
            await conn.execute(_INSERT_TOMBSTONE, user_id)
            # Tombstone AYRICA gerekli: silme sonrası gecikmiş bir
            # `workout.session` eventi gelirse (Kafka'da hâlâ kuyrukta),
            # `workout_snapshots` tüketicisi bu tabloyu kontrol edip satırı
            # DİRİLTMEZ (aşağıdaki `deleted_users`, `app/worker/
            # workout_consumer.py`'nin tombstone kontrolüyle aynı tablo).

    for pid in photo_post_ids:
        await run_in_threadpool(storage.delete_photo, str(pid))

    logger.info(
        "hesap silme işlendi user_id=%s silinen_arkadaşlık=%s silinen_antrenman=%s silinen_fotoğraf=%s",
        user_id, deleted_friendships, deleted_snapshots, len(photo_post_ids),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- chat-service'in cagirdigi ic uclar (Faz S6) -----------------------------
#
# `chat_db`'de ne arkadaslik ne de kullanici adi var (ADR 0005: veritabani
# basina servis). Bu iki uc, chat-service'in yazma yetkisini (arkadas mi) ve
# okuma goruntusunu (konusma listesindeki ad/kullanici adi) kurmasi icin
# gereken TEK senkron cagrilar — ADR 0005'in izin verdigi "minimum senkron
# cagri" istisnasi, `auth-service/app/worker/fanout.py`'nin silme cagrilarinin
# ayni sinifinda.


@router.get("/friendships/check")
async def check_friendship(
    a: uuid.UUID = Query(),
    b: uuid.UUID = Query(),
    x_internal_key: str | None = Header(default=None),
) -> dict:
    _require_internal_key(x_internal_key)
    if a == b:
        raise unprocessable("a ve b aynı olamaz")

    async with db.pool.acquire() as conn:
        result = await friendships.are_friends(conn, a, b)

    return {"are_friends": result}


@router.get("/profiles/batch")
async def batch_profiles(
    ids: str = Query(description="virgülle ayrılmış UUID listesi"),
    x_internal_key: str | None = Header(default=None),
) -> dict:
    _require_internal_key(x_internal_key)

    try:
        user_ids = [uuid.UUID(raw.strip()) for raw in ids.split(",") if raw.strip()]
    except ValueError:
        raise unprocessable("ids geçerli UUID'lerin virgülle ayrılmış listesi olmalı") from None

    if not user_ids:
        return {"items": []}

    async with db.pool.acquire() as conn:
        results = await profiles.find_by_user_ids(conn, user_ids)

    return {
        "items": [
            {
                "user_id": str(p.user_id),
                "username": p.username,
                "display_name": p.display_name,
                "avatar_seed": p.avatar_seed,
            }
            for p in results
        ]
    }
