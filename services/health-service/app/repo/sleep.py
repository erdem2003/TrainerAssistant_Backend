"""Gecelik uyku süresi — `health_users/{uid}/sleep/{yyyy-MM-dd}`.

★ SU'DAN FARKLI: EKLEME DEĞİL, ÜZERİNE YAZMA ★ Uyku tek ölçüm ve düzeltiliyor
("7 değil 7.5 saat"); birikimli bir uç iki kayıtta 14 saat üretirdi.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from app.db import user_doc


@dataclass(frozen=True)
class SleepRow:
    log_date: date
    minutes: int


def _col(user_id: uuid.UUID):
    return user_doc(user_id).collection("sleep")


async def fetch_day(user_id: uuid.UUID, day: date) -> SleepRow | None:
    snap = await _col(user_id).document(day.isoformat()).get()
    if not snap.exists:
        return None
    return SleepRow(log_date=day, minutes=int(snap.get("minutes")))


async def fetch_range(user_id: uuid.UUID, start: date, end: date) -> list[SleepRow]:
    col = _col(user_id)
    query = (
        col.where(filter=firestore.FieldFilter(FieldPath.document_id(), ">=", col.document(start.isoformat())))
        .where(filter=firestore.FieldFilter(FieldPath.document_id(), "<=", col.document(end.isoformat())))
        .order_by(FieldPath.document_id())
    )
    return [SleepRow(log_date=date.fromisoformat(s.id), minutes=int(s.get("minutes"))) async for s in query.stream()]


async def set_minutes(user_id: uuid.UUID, day: date, minutes: int) -> SleepRow:
    await _col(user_id).document(day.isoformat()).set({"minutes": minutes, "updated_at": firestore.SERVER_TIMESTAMP})
    return SleepRow(log_date=day, minutes=minutes)


async def delete_day(user_id: uuid.UUID, day: date) -> None:
    """Kaydı tamamen siler — `minutes = 0` yazmaktan FARKLI (0 = "hiç uyumadım",
    kayıt yok = "girmedim"; ortalamada farklı davranırlar)."""
    await _col(user_id).document(day.isoformat()).delete()
