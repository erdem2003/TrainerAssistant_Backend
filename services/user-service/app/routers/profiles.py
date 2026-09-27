"""GET/PUT /v1/users/me — profil okuma ve tam yazma (upsert)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header

from app.identity import require_user_id
from app.repo import profiles
from app.schemas import ProfileResponse, ProfileUpdate, UnitSystem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/users", tags=["profiles"])

# HealthMetrics.DEFAULT_DAILY_GOAL ile aynı. İki yerde duruyor çünkü Kotlin ve
# Python arasında paylaşılan bir sabit mekanizması yok; değiştirilirse ikisi
# birden değişmeli.
DEFAULT_DAILY_GOAL_REPS = 20


def _epoch_ms(value: datetime | None) -> int | None:
    """service-contract §6: zaman damgaları UTC epoch milisaniye."""
    if value is None:
        return None
    return int(value.timestamp() * 1000)


def _to_response(user_id: str, profile: profiles.Profile | None) -> ProfileResponse:
    """Satır yoksa BOŞ PROFİL döner — 404 değil."""
    if profile is None:
        return ProfileResponse(
            user_id=user_id,
            sex=None,
            age=None,
            weight_kg=None,
            height_cm=None,
            goal=None,
            unit_system=UnitSystem.METRIC,
            daily_goal_reps=DEFAULT_DAILY_GOAL_REPS,
            onboarding_completed_at=None,
            created_at=None,
            updated_at=None,
        )

    return ProfileResponse(
        user_id=str(profile.user_id),
        sex=profile.sex,
        age=profile.age,
        weight_kg=profile.weight_kg,
        height_cm=profile.height_cm,
        goal=profile.goal,
        unit_system=profile.unit_system,
        daily_goal_reps=profile.daily_goal_reps,
        onboarding_completed_at=_epoch_ms(profile.onboarding_completed_at),
        created_at=_epoch_ms(profile.created_at),
        updated_at=_epoch_ms(profile.updated_at),
    )


@router.get("/me", response_model=ProfileResponse)
async def get_me(x_user_id: str | None = Header(default=None)) -> ProfileResponse:
    user_id = require_user_id(x_user_id)

    profile = await profiles.find_by_id(user_id)

    return _to_response(str(user_id), profile)


@router.put("/me", response_model=ProfileResponse)
async def put_me(
    payload: ProfileUpdate,
    x_user_id: str | None = Header(default=None),
) -> ProfileResponse:
    """Profili tam olarak değiştirir; satır yoksa oluşturur."""
    user_id = require_user_id(x_user_id)

    # Zaman damgasını SUNUCU koyuyor, istemci değil. Yanlış ayarlı bir telefon
    # profili 2035'te tamamlanmış gösterebilirdi.
    completed_at = (
        datetime.now(timezone.utc) if payload.onboarding_completed else None
    )

    profile = await profiles.upsert(
        user_id,
        sex=payload.sex.value if payload.sex else None,
        age=payload.age,
        weight_kg=payload.weight_kg,
        height_cm=payload.height_cm,
        goal=payload.goal.value if payload.goal else None,
        unit_system=payload.unit_system.value,
        daily_goal_reps=payload.daily_goal_reps,
        onboarding_completed_at=completed_at,
    )

    logger.info("profil güncellendi user_id=%s", user_id)
    return _to_response(str(user_id), profile)
