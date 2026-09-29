"""POST/GET /v1/workouts — antrenman yazma (idempotent) ve gecmis okuma."""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Header, Query, Response, status
from google.cloud import firestore
from nabiz_firebase.deploy import standalone

from app import events, quests
from app.config import settings
from app.correlation import current_correlation_id
from app.db import db
from app.errors import conflict, not_found, unprocessable
from app.identity import require_user_id
from app.repo import exercises, outbox, progress, workouts
from app.schemas import (
    ExerciseOut,
    RepOut,
    SetOut,
    WorkoutIn,
    WorkoutOut,
    WorkoutPage,
    WorkoutSummary,
    epoch_ms,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["workouts"])


# --- Cursor kodlama ---------------------------------------------------------
# Cursor OPAK olmali (service-contract §5): istemci icini bilmemeli, yoksa
# bicimi degistirdigimizde eski istemciler kirilir. Base64 sifreleme degil,
# yalnizca "bunu ayristirma" isareti.

def _encode_cursor(started_at: datetime, workout_id: uuid.UUID) -> str:
    raw = f"{started_at.timestamp()}|{workout_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        ts_text, id_text = raw.split("|", 1)
        return (
            datetime.fromtimestamp(float(ts_text), tz=timezone.utc),
            uuid.UUID(id_text),
        )
    except (ValueError, binascii.Error, UnicodeDecodeError):
        # Bozuk cursor 500 degil 400 olmali: istemcinin gonderdigi veri hatali.
        raise unprocessable("Sayfalama imleci geçersiz") from None


# --- Yazma ------------------------------------------------------------------

@router.post("/workouts", response_model=WorkoutOut)
async def create_workout(
    payload: WorkoutIn,
    response: Response,
    background_tasks: BackgroundTasks,
    x_user_id: str | None = Header(default=None),
) -> WorkoutOut:
    """Antrenmanı kaydeder. AYNI ID İKİNCİ KEZ GELİRSE YENİ KAYIT AÇILMAZ.

    service-contract §4:
      201  ilk yazım
      200  aynı id, aynı içerik → mevcut kayıt döner, hata YOK
      409  aynı id, FARKLI içerik → gerçek çakışma

    Ağ hatasında tekrar denemek güvenli olmak zorunda. 409 dönmek yerine 200
    dönmek, mobil taraftaki senkron kuyruğunun kilitlenmemesini sağlıyor.
    """
    user_id = require_user_id(x_user_id)
    incoming_hash = payload.content_hash()

    document = workouts.build_document(
        user_id=user_id,
        exercise_id=payload.exercise_id,
        started_at_ms=payload.started_at,
        ended_at_ms=payload.ended_at,
        content_hash=incoming_hash,
        sets=payload.sets,
    )

    # ★ OLAY KENDI KENDINE YETERLI OLMALI ★
    # Tüketici (analytics, social) bu alanları görmek için workout-service'e
    # geri soramaz — ADR 0005. Hepsi gövdeden hesaplanıyor, ek sorgu YOK;
    # dokümanın toplamlarıyla AYNI sayılar (tek kaynak: build_document).
    event_payload = {
        "workout_id": str(payload.id),
        "user_id": str(user_id),
        "exercise_id": payload.exercise_id,
        "started_at": payload.started_at,
        "ended_at": payload.ended_at,
        "total_sets": document["total_sets"],
        "total_reps": document["total_reps"],
        "total_active_seconds": round(document["active_seconds"], 3),
        "reps_with_errors": document["reps_with_errors"],
        "best_set_reps": document["best_set_reps"],
        "form_errors": document["form_errors"],
    }
    cid = current_correlation_id()

    # TEK TRANSACTION: kimlik kaydı + antrenman + outbox olayı (ADR 0006/0019).
    # "Kayıt var ama olay yok" ya da tersi oluşamaz. Kimlik kaydı transaction
    # İÇİNDE okunuyor: iki eşzamanlı istek yarışırsa kaybeden Firestore
    # tarafından yeniden denenir ve bu sefer kaydı görüp idempotent dala düşer.
    @firestore.async_transactional
    async def write(tx) -> workouts.ExistingWorkout | None:
        existing = await workouts.get_existing_in_tx(tx, payload.id)
        if existing is not None:
            return existing
        if not exercises.exists(payload.exercise_id):
            raise unprocessable("Bilinmeyen egzersiz", {"exercise_id": payload.exercise_id})
        workouts.insert_in_tx(tx, payload.id, user_id, document)
        # XP antrenmanla aynı anda: kayıt varsa XP de var (günlük görev/seviye).
        progress.add_rep_xp_in_tx(tx, user_id, quests.rep_xp(document["total_reps"], document["reps_with_errors"]))
        outbox.enqueue(
            tx,
            event_type=events.EVENT_WORKOUT_COMPLETED,
            topic=events.TOPIC_WORKOUT_SESSION,
            partition_key=str(user_id),
            payload=event_payload,
            correlation_id=None if cid == "-" else cid,
        )
        return None

    existing = await write(db.client.transaction())

    if existing is not None:
        # BAŞKASININ KAYDI: 403 değil 404 (service-contract §3). 403 dönmek
        # o id'nin var olduğunu doğrulardı.
        if existing.user_id != user_id:
            raise not_found("Antrenman bulunamadı")

        if existing.content_hash != incoming_hash:
            raise conflict(
                "Bu antrenman id'si farklı bir içerikle zaten kayıtlı",
                {"workout_id": str(payload.id)},
            )

        response.status_code = status.HTTP_200_OK
        return await _load_detail(payload.id, user_id)

    # Commit oldu — olayı yoklama beklemeden dağıt. Tek süreçte döngüyü
    # uyandırmak yeter; Cloud Run'da (ADR 0020) istek bitince CPU kesildiği
    # için dağıtım bu isteğin arka plan görevinde yapılır. Başarısız olursa
    # olay kuyrukta kalır, zamanlayıcı `/internal/outbox/dispatch` ile toplar.
    if standalone():
        background_tasks.add_task(outbox.dispatcher().dispatch_pending)
    else:
        outbox.dispatcher().notify()

    logger.info(
        "antrenman kaydedildi workout_id=%s set=%d tekrar=%d",
        payload.id, document["total_sets"], document["total_reps"],
    )
    response.status_code = status.HTTP_201_CREATED
    return _to_out(payload.id, document)


# --- Okuma ------------------------------------------------------------------

@router.get("/workouts", response_model=WorkoutPage)
async def list_workouts(
    x_user_id: str | None = Header(default=None),
    limit: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
) -> WorkoutPage:
    """Antrenman geçmişi, en yeni üstte. Cursor sayfalama (service-contract §5)."""
    user_id = require_user_id(x_user_id)

    effective_limit = limit or settings.page_size_default
    if effective_limit > settings.page_size_max:
        effective_limit = settings.page_size_max

    cursor_started_at: datetime | None = None
    cursor_id: uuid.UUID | None = None
    if cursor:
        cursor_started_at, cursor_id = _decode_cursor(cursor)

    # Bir fazla çekiliyor: sonraki sayfa VAR MI sorusunu ayrı bir sayım
    # sorgusu olmadan cevaplamak için.
    rows = await workouts.fetch_page(
        user_id,
        cursor_started_at=cursor_started_at,
        cursor_id=cursor_id,
        limit=effective_limit + 1,
    )

    has_more = len(rows) > effective_limit
    page = rows[:effective_limit]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last.started_at, last.id)

    return WorkoutPage(
        items=[
            WorkoutSummary(
                id=str(row.id),
                exercise_id=row.exercise_id,
                started_at=epoch_ms(row.started_at),
                ended_at=epoch_ms(row.ended_at),
                total_sets=row.total_sets,
                total_reps=row.total_reps,
                reps_with_errors=row.reps_with_errors,
                total_active_seconds=row.active_seconds,
                best_set_reps=row.best_set_reps,
            )
            for row in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/workouts/{workout_id}", response_model=WorkoutOut)
async def get_workout(
    workout_id: uuid.UUID,
    x_user_id: str | None = Header(default=None),
) -> WorkoutOut:
    user_id = require_user_id(x_user_id)
    return await _load_detail(workout_id, user_id)


async def _load_detail(workout_id: uuid.UUID, user_id: uuid.UUID) -> WorkoutOut:
    """Başkasının antrenmanı kullanıcının altında YOK → 404 (var olmayanla
    ayırt edilemez, service-contract §3)."""
    document = await workouts.fetch_detail(workout_id, user_id)
    if document is None:
        raise not_found("Antrenman bulunamadı")
    return _to_out(workout_id, document)


def _to_out(workout_id: uuid.UUID, document: dict) -> WorkoutOut:
    """Doküman → yanıt. Setler ve tekrarlar yazımda zaten sıralı; yine de
    sıralanıyor ki elle düzeltilmiş bir doküman sözleşmeyi bozmasın."""
    ordered_sets = [
        SetOut(
            index=s["index"],
            started_at=s["started_at"],
            ended_at=s["ended_at"],
            rep_count=len(s["reps"]),
            reps=[
                RepOut(
                    index=r["index"],
                    duration_seconds=r["duration_seconds"],
                    eccentric_seconds=r["eccentric_seconds"],
                    concentric_seconds=r["concentric_seconds"],
                    rom=r["rom"],
                    form_errors=sorted(r["form_errors"]),
                )
                for r in sorted(s["reps"], key=lambda x: x["index"])
            ],
        )
        for s in sorted(document.get("sets") or [], key=lambda x: x["index"])
    ]

    return WorkoutOut(
        id=str(workout_id),
        exercise_id=document["exercise_id"],
        started_at=epoch_ms(document["started_at"]),
        ended_at=epoch_ms(document.get("ended_at")),
        total_sets=len(ordered_sets),
        total_reps=sum(s.rep_count for s in ordered_sets),
        sets=ordered_sets,
    )


# --- Egzersiz katalogu ------------------------------------------------------

@router.get("/exercises", response_model=list[ExerciseOut])
async def list_exercises() -> list[ExerciseOut]:
    """Katalog. Kimlik gerektirmiyor: herkese aynı statik veri."""
    return [
        ExerciseOut(
            id=row.id,
            display_name=row.display_name,
            required_view=row.required_view,
        )
        for row in exercises.list_all()
    ]
