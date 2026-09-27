"""Günlük su tüketimi — `health_users/{uid}/water/{yyyy-MM-dd}`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from app.db import db, user_doc

# Tek günde kaydedilebilecek üst sınır (Postgres'teki LEAST(..., 20000)).
MAX_DAY_ML = 20000


@dataclass(frozen=True)
class WaterRow:
    log_date: date
    amount_ml: int


def _col(user_id: uuid.UUID):
    return user_doc(user_id).collection("water")


async def fetch_day(user_id: uuid.UUID, day: date) -> WaterRow | None:
    snap = await _col(user_id).document(day.isoformat()).get()
    if not snap.exists:
        return None
    return WaterRow(log_date=day, amount_ml=int(snap.get("amount_ml")))


async def fetch_range(user_id: uuid.UUID, start: date, end: date) -> list[WaterRow]:
    col = _col(user_id)
    query = (
        col.where(filter=firestore.FieldFilter(FieldPath.document_id(), ">=", col.document(start.isoformat())))
        .where(filter=firestore.FieldFilter(FieldPath.document_id(), "<=", col.document(end.isoformat())))
        .order_by(FieldPath.document_id())
    )
    return [WaterRow(log_date=date.fromisoformat(s.id), amount_ml=int(s.get("amount_ml"))) async for s in query.stream()]


async def add(user_id: uuid.UUID, day: date, amount_ml: int) -> WaterRow:
    """Günün toplamına EKLER (birikimli, bilerek idempotent değil).

    ★ TRANSACTION, OKU-SONRA-YAZ DEĞİL ★ İki paralel "su ekle" aynı günü okuyup
    ayrı ayrı yazsaydı biri kaybolurdu — Postgres'teki `ON CONFLICT DO UPDATE`'in
    Firestore karşılığı. Üst sınır da aynı transaction'da kırpılıyor.
    """
    ref = _col(user_id).document(day.isoformat())

    @firestore.async_transactional
    async def run(tx) -> int:
        snap = await ref.get(transaction=tx)
        current = int(snap.get("amount_ml")) if snap.exists else 0
        total = min(current + amount_ml, MAX_DAY_ML)
        tx.set(ref, {"amount_ml": total, "updated_at": firestore.SERVER_TIMESTAMP})
        return total

    return WaterRow(log_date=day, amount_ml=await run(db.client.transaction()))


async def set_amount(user_id: uuid.UUID, day: date, amount_ml: int) -> WaterRow:
    """Günün toplamını DOĞRUDAN ayarlar (düzeltme için, idempotent)."""
    await _col(user_id).document(day.isoformat()).set({"amount_ml": amount_ml, "updated_at": firestore.SERVER_TIMESTAMP})
    return WaterRow(log_date=day, amount_ml=amount_ml)
