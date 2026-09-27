"""Kullanıcının tüm profil verisi — hesap silme için."""

from __future__ import annotations

import uuid

from app.db import db, user_doc


async def delete_all(user_id: uuid.UUID) -> int:
    """`user_users/{uid}` (profil) ve altındaki ölçüm/kalibrasyon dokümanlarını
    siler; silinen doküman sayısını döner."""
    return await db.client.recursive_delete(user_doc(user_id))
