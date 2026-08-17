"""POST/GET /v1/workouts — antrenman yazma (idempotent) ve gecmis okuma."""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Query, Response, status

from app import events
from app.config import settings
from app.db import db
from app.errors import conflict, not_found, unprocessable
from app.identity import require_user_id
from app.repo import exercises, outbox, workouts
from app.schemas import (
    ExerciseOut,
    RepOut,
    SetOut,
    WorkoutIn,
    WorkoutOut,
    WorkoutPage,
    WorkoutSummary,
    epoch_ms,
    from_epoch_ms,
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

    async with db.pool.acquire() as conn:
        existing = await workouts.find_existing(conn, payload.id)

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
            return await _load_detail(conn, payload.id, user_id)

        if not await exercises.exists(conn, payload.exercise_id):
            raise unprocessable(
                "Bilinmeyen egzersiz", {"exercise_id": payload.exercise_id}
            )

        # TEK TRANSACTION: yarım yazılmış bir antrenman (setleri olan ama
        # tekrarları olmayan) sessizce yanlış veri olurdu. Olay da aynı
        # transaction'da yazılıyor (outbox deseni, ADR 0006).
        async with conn.transaction():
            created = await workouts.insert_full(
                conn,
                workout_id=payload.id,
                user_id=user_id,
                exercise_id=payload.exercise_id,
                started_at=from_epoch_ms(payload.started_at),
                ended_at=(
                    from_epoch_ms(payload.ended_at)
                    if payload.ended_at is not None else None
                ),
                content_hash=incoming_hash,
                sets=[
                    _SetForInsert(
                        index=s.index,
                        started_at=from_epoch_ms(s.started_at),
                        ended_at=from_epoch_ms(s.ended_at),
                        reps=s.reps,
                    )
                    for s in payload.sets
                ],
            )

            if not created:
                # İki eşzamanlı istek yarıştı ve diğeri kazandı. Hata değil:
                # sonuç istenen durumla aynı.
                response.status_code = status.HTTP_200_OK
                return await _load_detail(conn, payload.id, user_id)

            total_reps = sum(len(s.reps) for s in payload.sets)

            # ★ OLAY KENDI KENDINE YETERLI OLMALI ★
            # Tüketici (analytics-service) bu alanları görmek için
            # workout-service'e geri soramaz — ADR 0005 başka servisin
            # veritabanına dokunmayı yasaklıyor ve senkron çağrı, olayın
            # sağladığı ayrışmayı ortadan kaldırırdı.
            #
            # Üçü de gövdeden hesaplanıyor, ek sorgu YOK:
            #   active_seconds   -> set süreleri (setler ARASI dinlenme hariç)
            #   reps_with_errors -> hatası olan tekrar sayısı
            #   form_errors      -> hata türü → kaç tekrarda görüldü
            active_seconds = sum(
                (s.ended_at - s.started_at) / 1000.0 for s in payload.sets
            )
            all_reps = [rep for s in payload.sets for rep in s.reps]
            form_error_counts: dict[str, int] = {}
            for rep in all_reps:
                for error in rep.form_errors:
                    form_error_counts[error] = form_error_counts.get(error, 0) + 1

            await outbox.enqueue(
                conn,
                events.EVENT_WORKOUT_COMPLETED,
                events.TOPIC_WORKOUT_SESSION,
                partition_key=str(user_id),
                payload={
                    "workout_id": str(payload.id),
                    "user_id": str(user_id),
                    "exercise_id": payload.exercise_id,
                    "started_at": payload.started_at,
                    "ended_at": payload.ended_at,
                    "total_sets": len(payload.sets),
                    "total_reps": total_reps,
                    "total_active_seconds": round(active_seconds, 3),
                    "reps_with_errors": sum(1 for r in all_reps if r.form_errors),
                    "best_set_reps": max((len(s.reps) for s in payload.sets), default=0),
                    "form_errors": form_error_counts,
                },
            )

        logger.info(
            "antrenman kaydedildi workout_id=%s set=%d tekrar=%d",
            payload.id, len(payload.sets), total_reps,
        )
        response.status_code = status.HTTP_201_CREATED
        return await _load_detail(conn, payload.id, user_id)


class _SetForInsert:
    """Repo katmanının beklediği sade taşıyıcı (epoch değil datetime ile)."""

    __slots__ = ("index", "started_at", "ended_at", "reps")

    def __init__(self, index: int, started_at: datetime,
                 ended_at: datetime, reps: list) -> None:
        self.index = index
        self.started_at = started_at
        self.ended_at = ended_at
        self.reps = reps


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

    async with db.pool.acquire() as conn:
        # Bir fazla çekiliyor: sonraki sayfa VAR MI sorusunu ayrı bir COUNT
        # sorgusu olmadan cevaplamak için.
        rows = await workouts.fetch_page(
            conn, user_id,
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
    async with db.pool.acquire() as conn:
        return await _load_detail(conn, workout_id, user_id)


async def _load_detail(conn, workout_id: uuid.UUID, user_id: uuid.UUID) -> WorkoutOut:
    """Düz JOIN sonucunu iç içe yapıya çevirir.

    Sorgu set × tekrar × hata kartezyeni döndürüyor; aynı tekrar birden çok
    hataya sahipse birden çok satırda görünür. Sözlükle tekilleştiriliyor.
    """
    rows = await workouts.fetch_detail(conn, workout_id, user_id)
    if not rows:
        raise not_found("Antrenman bulunamadı")

    head = rows[0]
    sets: dict[int, dict] = {}

    for row in rows:
        set_index = row["set_index"]
        if set_index is None:
            continue  # Seti olmayan antrenman (LEFT JOIN)

        entry = sets.setdefault(set_index, {
            "index": set_index,
            "started_at": row["set_started"],
            "ended_at": row["set_ended"],
            "reps": {},
        })

        rep_index = row["rep_index"]
        if rep_index is None:
            continue

        rep = entry["reps"].setdefault(rep_index, {
            "index": rep_index,
            "duration_seconds": row["duration_s"],
            "eccentric_seconds": row["eccentric_s"],
            "concentric_seconds": row["concentric_s"],
            "rom": row["rom"],
            "form_errors": set(),
        })
        if row["error"] is not None:
            rep["form_errors"].add(row["error"])

    ordered_sets = [
        SetOut(
            index=s["index"],
            started_at=epoch_ms(s["started_at"]),
            ended_at=epoch_ms(s["ended_at"]),
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
                for r in sorted(s["reps"].values(), key=lambda x: x["index"])
            ],
        )
        for s in sorted(sets.values(), key=lambda x: x["index"])
    ]

    return WorkoutOut(
        id=str(head["id"]),
        exercise_id=head["exercise_id"],
        started_at=epoch_ms(head["started_at"]),
        ended_at=epoch_ms(head["ended_at"]),
        total_sets=len(ordered_sets),
        total_reps=sum(s.rep_count for s in ordered_sets),
        sets=ordered_sets,
    )


# --- Egzersiz katalogu ------------------------------------------------------

@router.get("/exercises", response_model=list[ExerciseOut])
async def list_exercises() -> list[ExerciseOut]:
    """Katalog. Kimlik gerektirmiyor: herkese aynı statik veri."""
    async with db.pool.acquire() as conn:
        rows = await exercises.list_all(conn)
    return [
        ExerciseOut(
            id=row.id,
            display_name=row.display_name,
            required_view=row.required_view,
        )
        for row in rows
    ]
