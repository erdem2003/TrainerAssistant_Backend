"""DELETE /internal/users/{id} — hesap silindiginde sosyal veriyi temizler.
Gateway bu yolu yayinlamaz; yalnizca servisler arasi cagrilir.

Silme kapsami: profil (ad EMEKLI kilide doner), arkadasliklar (her iki taraf),
gonderiler (kaskadla begeni/yorum/klip), baskalarinin gonderisine birakilan
begeni/yorum, snapshot'lar + bildirimler (`social_users/{uid}` altinda),
meydan okuma katilimlari/kurduklari, kudos, fotograflar — ve bir TOMBSTONE
(`social_deleted_users`): gecikmeli ya da replay'deki bir `workout.session`
olayi silinmis kullanicinin snapshot'ini DIRILTMESIN (ADR 0014, Sonuclar).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, Query, Response, status
from starlette.concurrency import run_in_threadpool

from app import storage
from app.config import settings
from app.db import db, user_doc
from app.errors import ApiError, forbidden, unprocessable
from app.repo import (
    challenges,
    friendships,
    league,
    posts,
    processed_events,
    profiles,
    snapshots,
    tombstones,
)
from app.worker import workout_consumer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

EVENT_ACCOUNT_DELETED = "AccountDeleted"


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

    # ★ SIRA: ÖNCE SİL, SONRA İŞARETLE ★ (health-service deseni) — silme
    # adımları bir transaction'a sığmıyor ama her biri idempotent; arada
    # çökülürse yeniden teslimde kalan kısım silinir. Ters sıra veriyi
    # sonsuza kadar bırakırdı.
    if await processed_events.exists(event_id):
        logger.info("event zaten işlenmiş, atlanıyor event_id=%s", event_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Tombstone EN BAŞTA: silme sürerken gelen bir olay snapshot'ı yeniden
    # yazmasın.
    await tombstones.mark(user_id)

    deleted_friendships = await friendships.delete_all_for_user(user_id)
    await profiles.delete_and_retire(user_id)
    deleted_owners = await snapshots.delete_by_user(user_id)
    deleted_posts = await posts.delete_all_for_user(user_id)
    await challenges.delete_for_user(user_id)
    await challenges.delete_kudos_by_giver(user_id)
    await league.delete_for(user_id)
    # Snapshot'lar + KENDİ gelen kutusu. Bu kullanıcının başkasına AKTÖR olarak
    # bıraktığı bildirimler kalıyor — okuma yolu silinmiş aktörü "Silinmiş
    # kullanıcı" olarak gösteriyor (Postgres dalıyla aynı).
    await db.client.recursive_delete(user_doc(user_id))

    # Fotoğraflar Firestore silmesinden SONRA: ters sırada, silme yarıda
    # kalırsa fotoğrafı olmayan görünür gönderi kalırdı.
    photo_post_ids = [p.id for p in deleted_posts if p.photo_content_type is not None]
    for pid in photo_post_ids:
        await run_in_threadpool(storage.delete_photo, str(pid))

    await processed_events.claim(event_id, EVENT_ACCOUNT_DELETED)

    logger.info(
        "hesap silme işlendi user_id=%s silinen_arkadaşlık=%s silinen_antrenman=%s silinen_fotoğraf=%s",
        user_id, deleted_friendships, deleted_owners, len(photo_post_ids),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- chat-service'in cagirdigi ic uclar (Faz S6) -----------------------------
#
# chat-service'te ne arkadaslik ne de kullanici adi var (ADR 0005). Bu iki uc,
# chat-service'in yazma yetkisini (arkadas mi) ve okuma goruntusunu (konusma
# listesindeki ad) kurmasi icin gereken TEK senkron cagrilar.


@router.get("/friendships/check")
async def check_friendship(
    a: uuid.UUID = Query(),
    b: uuid.UUID = Query(),
    x_internal_key: str | None = Header(default=None),
) -> dict:
    _require_internal_key(x_internal_key)
    if a == b:
        raise unprocessable("a ve b aynı olamaz")

    return {"are_friends": await friendships.are_friends(a, b)}


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

    results = await profiles.find_by_user_ids(user_ids)

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


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
async def receive_event(
    envelope: dict,
    x_internal_key: str | None = Header(default=None),
) -> Response:
    """Outbox olayının HTTP ile teslimi (ADR 0020 — ayrı dağıtım).

    Süreç içi abonelikle AYNI işleyici; idempotency `processed_events`'te.
    İşleyici patlarsa 5xx döner ve üretici olayı kuyrukta tutup yeniden dener.
    """
    _require_internal_key(x_internal_key)
    await workout_consumer.handle(envelope)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sweep", status_code=status.HTTP_204_NO_CONTENT)
async def sweep_stale_posts(x_internal_key: str | None = Header(default=None)) -> Response:
    """Bayat PENDING_SNAPSHOT gönderilerini siler — Cloud Scheduler çağırır
    (ADR 0020; tek süreçte aynı işi `sweep_stale_posts_loop` yapıyor)."""
    _require_internal_key(x_internal_key)
    deleted = await posts.sweep_stale_pending()
    if deleted:
        logger.info("bayat PENDING_SNAPSHOT gönderi silindi adet=%d", deleted)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
