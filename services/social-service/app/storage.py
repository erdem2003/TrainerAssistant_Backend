"""MinIO nesne deposu istemcisi — motivasyon gönderisi fotoğrafları (ADR 0016).

★ AĞA AÇILMIYOR ★ Yalnızca social-service içeriden erişir. Mobil istemci
fotoğrafı asla doğrudan MinIO'dan çekmez — `GET /v1/social/posts/{id}/photo`
üzerinden, arkadaşlık kontrolünden geçerek social-service'in kendisi akıtır
(docs/architecture/overview.md §3, "tek public giriş: api-gateway").

`minio` SDK'sı SENKRON — bu modülün her fonksiyonu router tarafında
`starlette.concurrency.run_in_threadpool` ile sarmalanmalı, aksi halde tek
bir yükleme event loop'u tıkar.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def _client() -> Minio:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
    return client


def put_photo(post_id: str, data: bytes, content_type: str) -> None:
    _client().put_object(
        settings.minio_bucket,
        post_id,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def get_photo(post_id: str) -> tuple[bytes, str] | None:
    try:
        response = _client().get_object(settings.minio_bucket, post_id)
    except S3Error as exc:
        if exc.code == "NoSuchKey":
            return None
        raise
    try:
        data = response.read()
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        return data, content_type
    finally:
        response.close()
        response.release_conn()


def delete_photo(post_id: str) -> None:
    try:
        _client().remove_object(settings.minio_bucket, post_id)
    except S3Error as exc:
        # Zaten yok — hesap silme/idempotent tekrar bu yolu meşru geçer.
        if exc.code != "NoSuchKey":
            logger.warning("MinIO fotoğraf silme hatası post_id=%s: %s", post_id, exc)
