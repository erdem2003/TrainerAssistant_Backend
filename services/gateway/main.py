"""Tek süreçli giriş noktası (ADR 0019 karar 1 — modüler monolit).

Render'ın ücretsiz planında 750 saat/ay tek bir web servisine yetiyor; yedi
servis ayrı konteyner olsaydı ay bitmeden uyurdu. Bu dosya yedi servisi AYRI
PAKET olarak aynı süreçte yükler ve nginx gateway'inin yaptığı üç işi üstlenir:

  1. Yol → servis yönlendirmesi (`ROUTES`, eski `gateway.conf` location'ları).
  2. Kimlik: `FirebaseAuthMiddleware` Firebase ID token'ını doğrular, sahte
     kimlik başlıklarını siler ve `X-User-Id`'yi yazar (nginx `auth_request`).
  3. `/internal/*` dışarıya KAPALI — servisler arası çağrılar ağa hiç çıkmıyor,
     ASGI taşıyıcısıyla doğrudan hedef uygulamaya gidiyor (`_wire`).

★ NEDEN AYRI PAKET, TEK UYGULAMA DEĞİL ★ Her servis `app` adlı paketini
koruyor (database-per-service'in kod karşılığı: servisler birbirinin
modülünü içe aktaramaz). Aynı adlı yedi paket `sys.modules`'ta yan yana
duramayacağı için her biri yüklenirken geçici olarak `app*` girdileri
değiştiriliyor; yüklendikten sonra fonksiyonlar kendi modül globallerini
tuttuğu için çalışmaya devam ediyor. KISIT: istek yolunda fonksiyon içi
`from app...` içe aktarımı OLMAMALI (o an başka servisin `app`'i çözülür).
Aynı teknik `services/conftest.py`'deki zincir testlerinde kanıtlandı.

Çalıştırma (services/ klasöründen):
    uvicorn gateway.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import importlib
import logging
import os
import secrets
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from types import ModuleType

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

# Servisler arası anahtar: çağrılar süreç içinde kaldığı için dışarıdan hiç
# görülmüyor; ayarlanmamışsa her açılışta rastgele üretilir. Servis
# `settings`'leri içe aktarımda okunduğu için YÜKLEMEDEN ÖNCE atanmalı.
os.environ.setdefault("INTERNAL_API_KEY", secrets.token_urlsafe(32))

from nabiz_firebase import push_client  # noqa: E402
from nabiz_firebase.auth import FirebaseAuthMiddleware  # noqa: E402

logger = logging.getLogger("gateway")

SERVICES = ("user", "health", "auth", "analytics", "social", "chat", "workout")
"""Yükleme ve yaşam döngüsü sırası. Dağıtıcıyı başlatan workout EN SONDA:
abonelerini (analytics, social) kaydetmiş olsunlar."""

# Eski nginx `gateway.conf` location'larının aynısı. En uzun önek önce eşleşir.
ROUTES: dict[str, str] = {
    "/v1/auth": "auth",
    "/v1/users": "user",
    "/v1/measurements": "user",
    "/v1/calibration": "user",
    "/v1/workouts": "workout",
    "/v1/plan": "workout",
    "/v1/stats": "workout",
    "/v1/exercises": "workout",
    "/v1/water": "health",
    "/v1/sleep": "health",
    "/v1/analytics": "analytics",
    "/v1/social": "social",
    "/v1/chat": "chat",
    "/ws": "chat",
}
_ORDERED_ROUTES = sorted(ROUTES.items(), key=lambda item: len(item[0]), reverse=True)


def _is_app_module(name: str) -> bool:
    return name == "app" or name.startswith("app.")


def _load(service: str) -> tuple[object, dict[str, ModuleType]]:
    """`<service>-service/app/main.py`'yi diğer servislerden yalıtılmış yükler.

    Servisin `app*` modüllerini de döndürür — kablolama (`_wire`) onlara
    `sys.modules` üzerinden değil bu sözlükten erişir.
    """
    path = str(ROOT / f"{service}-service")
    saved = {k: v for k, v in sys.modules.items() if _is_app_module(k)}
    for name in saved:
        del sys.modules[name]
    sys.path.insert(0, path)
    try:
        app = importlib.import_module("app.main").app
        modules = {k: v for k, v in sys.modules.items() if _is_app_module(k)}
    finally:
        for name in [k for k in sys.modules if _is_app_module(k)]:
            del sys.modules[name]
        sys.modules.update(saved)
        sys.path.remove(path)
    return app, modules


def _import_in(service: str, modules: dict[str, ModuleType], name: str) -> ModuleType:
    """Servisin henüz içe aktarılmamış bir modülünü o servisin bağlamında yükler."""
    if name in modules:
        return modules[name]
    saved = {k: v for k, v in sys.modules.items() if _is_app_module(k)}
    for key in saved:
        del sys.modules[key]
    sys.modules.update(modules)
    path = str(ROOT / f"{service}-service")
    sys.path.insert(0, path)
    try:
        module = importlib.import_module(name)
        modules.update({k: v for k, v in sys.modules.items() if _is_app_module(k)})
    finally:
        for key in [k for k in sys.modules if _is_app_module(k)]:
            del sys.modules[key]
        sys.modules.update(saved)
        sys.path.remove(path)
    return module


apps: dict[str, object] = {}
_modules: dict[str, dict[str, ModuleType]] = {}
for _service in SERVICES:
    apps[_service], _modules[_service] = _load(_service)


def _wire() -> None:
    """Servisler arası senkron çağrıları süreç içine bağlar."""
    # chat → social: arkadaşlık kontrolü + profil toplu çekimi.
    social_client = _import_in("chat", _modules["chat"], "app.social_client")
    social_client.use_transport(httpx.ASGITransport(app=apps["social"]), "http://social.internal")
    # chat/social → user: push bildirimi (`POST /internal/push`).
    push_client.use_transport(httpx.ASGITransport(app=apps["user"]), "http://user.internal")
    # auth → herkes: hesap silme fan-out'u (`DELETE /internal/users/{id}`).
    fanout = _import_in("auth", _modules["auth"], "app.worker.fanout")
    fanout.use_apps({f"{name}-service": apps[name] for name in SERVICES if name != "auth"})


_wire()


async def _send_json(send, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


_NOT_FOUND = b'{"error":{"code":"NOT_FOUND","message":"Kaynak bulunamadi"}}'


async def _health(scope, send) -> None:
    if scope["path"] == "/health/ready":
        # Firestore'a gerçek bir okuma: kimlik bilgisi + ağ doğrulanır.
        db = _modules["health"]["app.db"].db
        ok = await db.healthy()
        await _send_json(send, 200 if ok else 503, b'{"status":"ready"}' if ok else b'{"status":"unavailable"}')
        return
    # /health/live — Render sağlık kontrolü ve uyanık tutma ping'i buraya.
    await _send_json(send, 200, b'{"status":"live"}')


async def router(scope, receive, send):
    if scope["type"] == "lifespan":
        return await _lifespan(scope, receive, send)

    path: str = scope["path"]
    if path.startswith("/health/"):
        if scope["type"] == "http":
            return await _health(scope, send)
    elif not path.startswith("/internal"):
        for prefix, service in _ORDERED_ROUTES:
            if path == prefix or path.startswith(prefix + "/"):
                return await apps[service](scope, receive, send)

    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 4404})
        return None
    return await _send_json(send, 404, _NOT_FOUND)


@asynccontextmanager
async def _services_lifespan():
    async with AsyncExitStack() as stack:
        for service in SERVICES:
            app = apps[service]
            await stack.enter_async_context(app.router.lifespan_context(app))
            logger.info("%s-service açıldı", service)
        yield


async def _lifespan(scope, receive, send) -> None:
    """ASGI lifespan: yedi servisin açılış/kapanışını sırayla koşar."""
    message = await receive()
    assert message["type"] == "lifespan.startup"
    context = _services_lifespan()
    try:
        await context.__aenter__()
    except Exception as exc:  # noqa: BLE001 — uvicorn'a nedenini bildir
        logger.exception("açılış başarısız")
        await send({"type": "lifespan.startup.failed", "message": str(exc)})
        return
    await send({"type": "lifespan.startup.complete"})
    message = await receive()
    assert message["type"] == "lifespan.shutdown"
    try:
        await context.__aexit__(None, None, None)
    finally:
        await send({"type": "lifespan.shutdown.complete"})


# Dış katman kimlik, iç katman yönlendirme. Ara katman lifespan olaylarını
# olduğu gibi geçiriyor.
app = FirebaseAuthMiddleware(router)
