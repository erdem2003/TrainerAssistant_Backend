"""FastAPI uygulamasi: acilis/kapanis, middleware, hata isleyicileri, router kaydi."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request

from nabiz_firebase.deploy import install_auth, subscribe_http_from_env

from app.config import settings
from app.correlation import (
    CorrelationMiddleware,
    configure_logging,
    current_correlation_id,
)
from app.db import db
from app.errors import ApiError, api_error_handler, unhandled_error_handler
from app.repo import outbox
from app.routers import challenges, health, internal, plan, quests, stats, workouts

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    await db.connect()
    # Migration açılışta koşuyor. Ayrı bir komut olsaydı "önce migrate et, sonra
    # başlat" sırasını herkesin hatırlaması gerekirdi; unutulduğunda hata
    # veritabanı seviyesinde ve anlaşılmaz çıkar.
    await db.migrate()
    # Kafka relay sürecinin yerini alan süreç içi dağıtıcı (ADR 0019 karar 2).
    # Abonelerini (analytics, social) tek süreçli giriş noktası kaydeder.
    dispatcher = outbox.dispatcher()
    # ADR 0020: ayrı dağıtımda aboneler (analytics, social) HTTP ile bağlanır.
    subscribe_http_from_env(settings.internal_api_key)
    if settings.outbox_dispatcher_enabled:
        dispatcher.start()
    logger.info("%s hazır", settings.service_name)
    try:
        yield
    finally:
        await dispatcher.stop()
        await db.close()

app = FastAPI(
    title="workout-service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(CorrelationMiddleware)
# ADR 0020: ayrı dağıtımda Firebase token'ını servis kendisi doğrular.
install_auth(app)

app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic doğrulama hatalarını sözleşme biçimine çevirir."""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Gönderilen veri geçersiz",
                "details": {
                    "fields": [
                        {
                            "field": ".".join(str(part) for part in err["loc"][1:]),
                            "message": err["msg"],
                        }
                        for err in exc.errors()
                    ]
                },
                "correlation_id": current_correlation_id(),
            }
        },
    )

app.include_router(health.router)
app.include_router(workouts.router)
app.include_router(plan.router)
app.include_router(stats.router)
app.include_router(quests.router)
app.include_router(challenges.router)
app.include_router(internal.router)
