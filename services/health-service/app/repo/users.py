"""Kullanıcının tüm sağlık verisi — hesap silme için."""

from __future__ import annotations

import uuid

from app.db import db, user_doc


async def delete_all(user_id: uuid.UUID) -> int:
    """`health_users/{uid}` ve altındaki su/uyku dokümanlarını siler; silinen sayı."""
    return await db.client.recursive_delete(user_doc(user_id))
