"""Firebase kimliği → servislerin beklediği UUID.

Servisler kullanıcı kimliğini her yerde `uuid.UUID` olarak taşıyor (X-User-Id,
tablo anahtarları, olaylar). Firebase uid'i ise 28 karakterlik bir metin. Her
servisi değiştirmek yerine gateway katmanı uid'i **deterministik** bir UUID'ye
çevirir: aynı uid her zaman aynı UUID, çakışma olasılığı UUIDv5 kadar.

Ters yön (UUID → uid) gerektiğinde (ör. Firestore kuralları, bildirim) auth
servisindeki `auth_accounts/{uuid}` dokümanı uid'i saklar.
"""

from __future__ import annotations

import uuid

# Sabit ad alanı — DEĞİŞTİRİLMEZ; değişirse tüm kullanıcıların verisi "kaybolur".
NABIZ_UID_NAMESPACE = uuid.UUID("6f1c2a52-3d0e-4b7e-9a31-5c2f8d7e41a9")


def user_uuid_for(firebase_uid: str) -> uuid.UUID:
    return uuid.uuid5(NABIZ_UID_NAMESPACE, firebase_uid)
