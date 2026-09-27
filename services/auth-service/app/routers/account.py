"""DELETE /v1/auth/account — hesap silme (ADR 0019).

★ GÖVDE YOK ★ Parola artık bu serviste değil. İstemci çağırmadan hemen önce
Firebase ile YENİDEN kimlik doğruluyor (reauthenticate) — "token yetmez,
kanıt da iste" kuralı Firebase tarafında uygulanıyor.

★ AKIŞ — SENKRON FAN-OUT, SONRA FIREBASE ★
  1. Her servisin `DELETE /internal/users/{id}` ucu çağrılır (fanout.py).
     `X-Event-Id` kullanıcıdan DETERMİNİSTİK türetiliyor: istek yarıda kalıp
     istemci tekrar denerse aynı olay kimliği gider, bitmiş servisler
     `processed_events` sayesinde atlar, kalanlar tamamlanır.
  2. Hepsi başarılıysa Firebase kullanıcısı Admin SDK ile silinir.
  3. En son `auth_accounts` dokümanı.
Bir servis başarısız olursa 503 döner ve Firebase kullanıcısı SİLİNMEZ —
kullanıcı giriş yapıp tekrar deneyebilir. Ters sıra (önce Firebase) başarısız
bir fan-out'ta verisi duran ama giriş yapamayan, silmeyi yeniden
tetikleyemeyen bir hesap bırakırdı.

Postgres dalında outbox + ayrı worker vardı (204 hemen, fan-out arka planda).
Tek süreçli ücretsiz dağıtımda arka plan worker'ı yok (ADR 0019); fan-out
isteğin içinde, idempotent ve yeniden denenebilir. "Hesabın silindi" e-postası
KALKTI (SMTP worker istek yolundan çıkarıldı).
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Header, Response, status
from nabiz_firebase import auth as firebase_auth

from app import events
from app.errors import ApiError
from app.repo import accounts
from app.worker import fanout

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["account"])

# Sabit ad alanı — DEĞİŞTİRİLMEZ; değişirse yarıda kalmış silmelerin tekrarı
# farklı olay kimliğiyle gider (zararsız ama idempotency'yi boşa çıkarır).
_DELETION_EVENT_NAMESPACE = uuid.UUID("9a4b2c1e-7d3f-4e8a-b6c5-0f1e2d3c4b5a")


def deletion_event_id(user_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_DELETION_EVENT_NAMESPACE, str(user_id))


def _unauthorized() -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Oturum geçersiz, tekrar giriş yap")


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(x_user_id: str | None = Header(default=None)) -> Response:
    """Hesabı ve tüm servislerdeki verisini kalıcı olarak siler."""
    if not x_user_id:
        raise _unauthorized()
    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise _unauthorized() from None

    account = await accounts.find_by_id(user_id)
    if account is None:
        # Zaten silinmiş. İstenen durum bu — hata değil (idempotent).
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    event_id = str(deletion_event_id(user_id))
    try:
        await fanout.dispatch(event_id, events.EVENT_ACCOUNT_DELETED, {"user_id": str(user_id)})
    except fanout.FanoutFailed as exc:
        logger.warning("hesap silme fan-out'u tamamlanamadı user_id=%s: %s", user_id, exc)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DELETION_INCOMPLETE",
            "Hesap silme şu an tamamlanamadı, birazdan tekrar dene",
        ) from None

    await asyncio.to_thread(firebase_auth.delete_firebase_user, account.firebase_uid)
    await accounts.delete(user_id)
    firebase_auth.registry.forget(user_id)

    logger.info("hesap silindi user_id=%s", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
