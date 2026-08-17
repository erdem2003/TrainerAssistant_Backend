"""Correlation ID uretimi/tasinmasi ve log bicimi (service-contract §10)."""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HEADER = "X-Correlation-Id"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def current_correlation_id() -> str:
    return _correlation_id.get()


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Gelen id'yi korur, yoksa üretir; yanıta da yazar."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(HEADER)
        cid = incoming or uuid.uuid4().hex
        token = _correlation_id.set(cid)
        try:
            response = await call_next(request)
            response.headers[HEADER] = cid
            return response
        finally:
            _correlation_id.reset(token)


class CorrelationFilter(logging.Filter):
    """Her log satırına correlation id ekler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = current_correlation_id()
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(correlation_id)s] %(name)s: %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
