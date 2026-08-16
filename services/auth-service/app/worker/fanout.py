"""Event'leri diger servislere HTTP ile yansitir (Phase 10 koprusu, Phase 11'de Kafka)."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from app import events
from app.config import settings

logger = logging.getLogger(__name__)


class FanoutFailed(Exception):
    """Karşı servis ulaşılamadı ya da hata döndü — outbox satırı tekrar denenmeli."""


def _delete_user_data(event_id: str, user_id: str) -> None:
    """`user-service`'e profil silme çağrısı."""
    url = f"{settings.user_service_url}/internal/users/{user_id}"
    request = urllib.request.Request(url, method="DELETE")
    request.add_header("X-Internal-Key", settings.internal_api_key)
    request.add_header("X-Event-Id", event_id)

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status not in (200, 204):
                raise FanoutFailed(f"user-service {response.status} döndü")
    except urllib.error.HTTPError as exc:
        raise FanoutFailed(f"user-service {exc.code} döndü") from exc
    except urllib.error.URLError as exc:
        raise FanoutFailed(f"user-service'e ulaşılamadı: {exc.reason}") from exc


def dispatch(event_id: str, event_type: str, payload: dict) -> None:
    """Event'in diğer servislere yansıtılması. Çoğu event için hiçbir şey yapmaz."""
    if event_type != events.EVENT_ACCOUNT_DELETED:
        return

    user_id = payload.get("user_id")
    if not user_id:
        # Yeniden denemek düzeltmez — bozuk payload.
        logger.error("AccountDeleted payload'ında user_id yok event_id=%s", event_id)
        return

    _delete_user_data(event_id, user_id)
    logger.info("user-service'e silme bildirildi user_id=%s", user_id)
