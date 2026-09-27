"""Firebase Storage — motivasyon gönderisi fotoğrafları (ADR 0016, ADR 0019 karar 4).

MinIO'nun yerini aldı. Nesne yolu `posts/{postId}/photo`, kova
`nabiz-trainer.firebasestorage.app` (`FIREBASE_STORAGE_BUCKET` ile değişir).

★ ŞİMDİLİK SERVİS ÜZERİNDEN ★ Yükleme ve okuma hâlâ
`POST /v1/social/posts/motivation` ve `GET /v1/social/posts/{id}/photo` uçlarından
geçiyor — mobil sözleşme değişmedi. ADR 0019'un hedefi istemcinin doğrudan
Storage'a yüklemesi (kural: yalnız yazar yazar, oturum açmış herkes okur);
geçildiğinde bu modül yalnızca silme için kalır.

`google-cloud-storage` SENKRON — router bu fonksiyonları
`run_in_threadpool` ile çağırıyor (MinIO sürümüyle aynı sözleşme), aksi hâlde
tek bir yükleme olay döngüsünü tıkar.
"""

from __future__ import annotations

import logging

from google.api_core.exceptions import NotFound
from nabiz_firebase.admin import firebase_app

logger = logging.getLogger(__name__)


def photo_path(post_id: str) -> str:
    return f"posts/{post_id}/photo"


def _bucket():
    from firebase_admin import storage  # noqa: PLC0415 — yalnızca kullanılınca yüklensin

    return storage.bucket(app=firebase_app())


def put_photo(post_id: str, data: bytes, content_type: str) -> None:
    _bucket().blob(photo_path(post_id)).upload_from_string(data, content_type=content_type)


def get_photo(post_id: str) -> tuple[bytes, str] | None:
    blob = _bucket().get_blob(photo_path(post_id))
    if blob is None:
        return None
    return blob.download_as_bytes(), blob.content_type or "application/octet-stream"


def delete_photo(post_id: str) -> None:
    try:
        _bucket().blob(photo_path(post_id)).delete()
    except NotFound:
        # Zaten yok — hesap silme/idempotent tekrar bu yolu meşru geçer.
        return
    except Exception:
        logger.warning("Storage fotoğraf silme hatası post_id=%s", post_id, exc_info=True)
