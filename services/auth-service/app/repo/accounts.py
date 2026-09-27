"""`auth_accounts/{user_uuid}` — UUID ↔ Firebase uid eşlemesi (yazan: auth ara katmanı)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.db import db


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    firebase_uid: str
    email: str | None
    email_verified: bool
    created_at: datetime


def _ref(user_id: uuid.UUID):
    return db.collection("accounts").document(str(user_id))


async def find_by_id(user_id: uuid.UUID) -> Account | None:
    snap = await _ref(user_id).get()
    if not snap.exists:
        return None
    d = snap.to_dict()
    return Account(
        id=user_id,
        firebase_uid=d["firebase_uid"],
        email=d.get("email"),
        email_verified=bool(d.get("email_verified")),
        created_at=d["created_at"],
    )


async def delete(user_id: uuid.UUID) -> None:
    await _ref(user_id).delete()
