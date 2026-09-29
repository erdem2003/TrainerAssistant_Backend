"""`workout.session` tüketicisi — davet edilen ilk antrenmanını bitirince davet ödülü.

Tek süreçte `nabiz_firebase.outbox` dağıtıcısına abone olur (`register`); ayrı
dağıtımda (Cloud Run) aynı `handle` `/internal/events` ucundan çağrılır.
Grup adı her iki yolda aynı (`settings.referral_consumer_group`).

İdempotent: davet kaydı yalnız `pending` iken tamamlanır; olay tekrar gelirse
hiçbir şey olmaz.
"""

from __future__ import annotations

import logging
import uuid

from nabiz_firebase import outbox as shared_outbox

from app.config import settings
from app.repo import referrals, rewards

logger = logging.getLogger(__name__)

EVENT_WORKOUT_COMPLETED = "WorkoutCompleted"


async def handle(envelope: dict) -> bool:
    if envelope.get("event_type") != EVENT_WORKOUT_COMPLETED:
        return False
    try:
        user_id = uuid.UUID(str((envelope.get("payload") or {}).get("user_id")))
    except ValueError:
        logger.warning("davet tüketicisi: user_id yok event_id=%s", envelope.get("event_id"))
        return False
    done = await referrals.complete(user_id, rewards.utc_now())
    if done:
        logger.info("davet tamamlandı, iki tarafa Nabız+ verildi invitee=%s", user_id)
    return done


def register() -> None:
    shared_outbox.subscribe(settings.topic_workout_session, settings.referral_consumer_group, handle)


def unregister() -> None:
    shared_outbox.unsubscribe(settings.topic_workout_session, settings.referral_consumer_group)
