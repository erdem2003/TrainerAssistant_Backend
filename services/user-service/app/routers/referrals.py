"""Davet et, kazan.

GET  /v1/referrals/me       kendi davet kodun + kaç kişi davet ettin
POST /v1/referrals/redeem   yeni kullanıcı davet kodunu girer (ilk 7 gün, bir kez)
"""

from __future__ import annotations

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, Field

from app.errors import ApiError
from app.identity import require_user_id
from app.repo import profiles, referrals, rewards

router = APIRouter(prefix="/v1/referrals", tags=["referrals"])

_STATUS_BY_CODE = {
    "REFERRAL_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "REFERRAL_SELF": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "REFERRAL_TOO_LATE": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "REFERRAL_ALREADY_USED": status.HTTP_409_CONFLICT,
}


class ReferralOut(BaseModel):
    code: str
    invited: int
    completed: int
    referred: bool
    reward_days: int


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=16)


@router.get("/me", response_model=ReferralOut)
async def my_referral(x_user_id: str | None = Header(default=None)) -> ReferralOut:
    user_id = require_user_id(x_user_id)
    s = await referrals.stats(user_id)
    return ReferralOut(
        code=s.code, invited=s.invited, completed=s.completed, referred=s.referred_by is not None,
        reward_days=referrals.REFERRAL_REWARD.days,
    )


@router.post("/redeem", response_model=ReferralOut)
async def redeem(payload: RedeemIn, x_user_id: str | None = Header(default=None)) -> ReferralOut:
    """Ödül burada VERİLMEZ: davet edilen ilk antrenmanını bitirince iki tarafa verilir."""
    user_id = require_user_id(x_user_id)
    profile = await profiles.find_by_id(user_id)
    try:
        await referrals.redeem(user_id, payload.code, profile.created_at if profile else None, rewards.utc_now())
    except referrals.RedeemError as exc:
        raise ApiError(_STATUS_BY_CODE[exc.code], exc.code, exc.message) from None
    return await my_referral(str(user_id))
