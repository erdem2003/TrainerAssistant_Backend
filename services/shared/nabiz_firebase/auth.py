"""Firebase ID token → servislerin beklediği kimlik başlıkları (ADR 0019 karar 3).

nginx `auth_request` + auth-service `/introspect` deseninin tek süreçli
karşılığı. Servisler DEĞİŞMİYOR: kimliği hâlâ `X-User-Id` başlığından okuyor
(service-contract §2); bu ara katman başlığı Firebase token'ından üretiyor.

Başlıklar (eski gateway ile aynı adlar):
    X-User-Id         user_uuid_for(firebase uid)   — servislerin tek kimliği
    X-Email-Verified  "true" / "false"
    X-Token-Exp       token bitişi, epoch MİLİSANİYE (service-contract §6)
    X-Firebase-Uid    ham Firebase uid (yalnızca Firebase API'si gereken yer için)

★ SAHTE BAŞLIK KABUL EDİLMEZ ★ İstemcinin gönderdiği bu başlıklar HER istekte
silinip yalnızca doğrulanmış token'dan yeniden yazılıyor. Silinmeseydi
token'sız bir istek `X-User-Id: <başkası>` ile her servise o kişi olarak
girebilirdi — nginx'te `proxy_set_header` bunu yapıyordu.

★ TOKEN YOKSA GEÇİR, GEÇERSİZSE 401 ★ Açık uçlar (`/health/*`,
`/v1/exercises`) token'sız çalışmaya devam ediyor; kimlik isteyen uçlar zaten
`X-User-Id` yoksa 401 dönüyor (`require_user_id`). Token GÖNDERİLİP geçersizse
ara katman hemen 401 döner — süresi dolmuş token sessizce "anonim" sayılmasın.

★ İLK GÖRÜŞTE HESAP KAYDI ★ `auth_accounts/{uuid}` → {firebase_uid, email,
email_verified, created_at}: UUID → uid ters yönü (hesap silme, bildirim) ve
`/v1/auth/me` bunun üzerinden. Süreç içi önbellek her istekte okuma yapılmasın
diye (okuma kotası); doküman `create()` ile yazılıyor, iki eşzamanlı ilk
istek çift kayıt üretemez. Aynı anda `nabiz_uid` özel talebi (custom claim)
kullanıcıya yazılıyor: Firestore güvenlik kuralları (mobil dinleyiciler)
yalnızca `request.auth` görür, UUIDv5'i hesaplayamaz — kural
`request.auth.token.nabiz_uid in resource.data.participants` ile kontrol eder.
Talep bir sonraki token yenilemesinde görünür.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from nabiz_firebase.admin import firebase_app
from nabiz_firebase.firestore import firestore_client
from nabiz_firebase.identity import user_uuid_for

logger = logging.getLogger(__name__)

ACCOUNTS_COLLECTION = "auth_accounts"

HEADER_USER_ID = b"x-user-id"
HEADER_EMAIL_VERIFIED = b"x-email-verified"
HEADER_TOKEN_EXP = b"x-token-exp"
HEADER_FIREBASE_UID = b"x-firebase-uid"
_IDENTITY_HEADERS = {HEADER_USER_ID, HEADER_EMAIL_VERIFIED, HEADER_TOKEN_EXP, HEADER_FIREBASE_UID}


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    user_id: uuid.UUID
    firebase_uid: str
    email: str | None
    email_verified: bool
    expires_at_ms: int


def verify_id_token(token: str) -> dict:
    """Senkron (firebase-admin anahtarları ağdan çekip önbellekliyor) —
    çağıran thread'e atıyor. Testler bu fonksiyonu değiştirebilir."""
    from firebase_admin import auth  # noqa: PLC0415

    return auth.verify_id_token(token, app=firebase_app())


def set_uuid_claim(firebase_uid: str, user_id: uuid.UUID) -> None:
    from firebase_admin import auth  # noqa: PLC0415

    user = auth.get_user(firebase_uid, app=firebase_app())
    claims = dict(user.custom_claims or {})
    if claims.get("nabiz_uid") != str(user_id):
        claims["nabiz_uid"] = str(user_id)
        auth.set_custom_user_claims(firebase_uid, claims, app=firebase_app())


def delete_firebase_user(firebase_uid: str) -> None:
    """Hesap silmenin son adımı. Kullanıcı zaten yoksa hata değil (idempotent)."""
    from firebase_admin import auth  # noqa: PLC0415

    try:
        auth.delete_user(firebase_uid, app=firebase_app())
    except auth.UserNotFoundError:
        logger.info("Firebase kullanıcısı zaten yok uid=%s", firebase_uid)


async def verify_bearer(authorization: str | None) -> Identity | None:
    """`None` = token yok. Geçersiz token `InvalidToken` fırlatır."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise InvalidToken("Bearer biçimi değil")
    try:
        claims = await asyncio.to_thread(verify_id_token, token)
    except Exception as exc:  # firebase-admin'in hata sınıfları çeşitli
        raise InvalidToken(type(exc).__name__) from exc
    firebase_uid = claims.get("uid") or claims.get("sub")
    if not firebase_uid:
        raise InvalidToken("uid yok")
    return Identity(
        user_id=user_uuid_for(firebase_uid),
        firebase_uid=firebase_uid,
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified", False)),
        expires_at_ms=int(claims.get("exp", 0)) * 1000,
    )


class AccountRegistry:
    """`auth_accounts` yazımı + süreç içi önbellek (uuid → email_verified)."""

    def __init__(self) -> None:
        self._seen: dict[uuid.UUID, bool] = {}

    def forget(self, user_id: uuid.UUID) -> None:
        self._seen.pop(user_id, None)

    async def ensure(self, identity: Identity) -> None:
        if self._seen.get(identity.user_id) == identity.email_verified:
            return
        ref = firestore_client().collection(ACCOUNTS_COLLECTION).document(str(identity.user_id))
        data = {
            "firebase_uid": identity.firebase_uid,
            "email": identity.email,
            "email_verified": identity.email_verified,
        }
        try:
            await ref.create({**data, "created_at": firestore.SERVER_TIMESTAMP})
            first_sight = True
        except AlreadyExists:
            # Doğrulama durumu değişmiş olabilir (e-posta sonradan doğrulandı).
            await ref.update(data)
            first_sight = False
        if first_sight:
            try:
                await asyncio.to_thread(set_uuid_claim, identity.firebase_uid, identity.user_id)
            except Exception:
                # Talep yazılamazsa istek YİNE geçer: talep yalnızca istemcinin
                # doğrudan Firestore dinleyicileri için. Bir sonraki ilk görüşte
                # (süreç yeniden başlayınca) tekrar denenir.
                logger.warning("nabiz_uid talebi yazılamadı user_id=%s", identity.user_id, exc_info=True)
        self._seen[identity.user_id] = identity.email_verified


registry = AccountRegistry()


def _unauthorized_body() -> bytes:
    return json.dumps({
        "error": {
            "code": "INVALID_TOKEN",
            "message": "Oturum geçersiz, tekrar giriş yap",
            "details": {},
            "correlation_id": None,
        }
    }).encode("utf-8")


class FirebaseAuthMiddleware:
    """Saf ASGI ara katmanı (HTTP + WebSocket). Tek süreçli giriş noktasında
    TÜM servis uygulamalarının önüne bir kez takılır.

    WebSocket'te tarayıcı/OkHttp `Authorization` başlığı gönderebildiği için
    aynı yol; geçersiz token'da el sıkışma 4401 ile kapanır.
    """

    def __init__(self, app, *, registry: AccountRegistry = registry) -> None:
        self.app = app
        self.registry = registry

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() not in _IDENTITY_HEADERS]
        authorization = next((v.decode("latin-1") for k, v in headers if k.lower() == b"authorization"), None)

        try:
            identity = await verify_bearer(authorization)
        except InvalidToken as exc:
            logger.info("geçersiz Firebase token: %s path=%s", exc, scope.get("path"))
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401})
                return None
            body = _unauthorized_body()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return None

        if identity is not None:
            await self.registry.ensure(identity)
            headers += [
                (HEADER_USER_ID, str(identity.user_id).encode()),
                (HEADER_EMAIL_VERIFIED, b"true" if identity.email_verified else b"false"),
                (HEADER_TOKEN_EXP, str(identity.expires_at_ms).encode()),
                (HEADER_FIREBASE_UID, identity.firebase_uid.encode()),
            ]

        return await self.app({**scope, "headers": headers}, receive, send)
