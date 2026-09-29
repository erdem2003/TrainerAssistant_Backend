"""Ödüllü reklam uçları — "Nabız+" (24 saat reklamsız + gelişmiş analiz) ve seri dondurma.

GET  /v1/rewards/ssv             AdMob'un sunucu doğrulama çağrısı (KİMLİKSİZ, imzalı)
GET  /v1/rewards                 kullanıcının ödül durumu
POST /v1/rewards/streak-freeze   bir dondurma hakkıyla kaçırılan günü korur

Ödeme sistemi YOK (sahip kararı): avantajlar yalnız ödüllü video izlenerek açılır.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel

from app import ssv
from app.errors import ApiError, forbidden, unprocessable
from app.identity import require_user_id
from app.repo import rewards

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/rewards", tags=["rewards"])


class RewardStateOut(BaseModel):
    plus_active: bool
    plus_until: int | None
    streak_freezes: int
    max_streak_freezes: int
    freeze_days: list[str]


class StreakFreezeIn(BaseModel):
    date: str


def _out(state: rewards.RewardState) -> RewardStateOut:
    now = rewards.utc_now()
    return RewardStateOut(
        plus_active=state.plus_active(now),
        plus_until=int(state.plus_until.timestamp() * 1000) if state.plus_until else None,
        streak_freezes=state.streak_freezes,
        max_streak_freezes=rewards.MAX_STREAK_FREEZES,
        freeze_days=state.freeze_days,
    )


@router.get("/ssv", include_in_schema=False)
async def admob_ssv(request: Request) -> Response:
    """AdMob, izleme bitince çağırır. 200 dışı yanıtta AdMob yeniden dener; bu yüzden
    tekrar (duplicate) ve günlük sınır da 200 döner — yalnız sahte imza reddedilir."""
    raw = request.url.query
    try:
        await ssv.verify(raw)
    except ssv.SsvError as exc:
        logger.warning("SSV reddedildi: %s", exc)
        raise forbidden() from None

    params = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    reward, transaction_id = params.get("custom_data", ""), params.get("transaction_id", "")
    try:
        user_id = uuid.UUID(params.get("user_id", ""))
    except ValueError:
        # AdMob konsolu SSV adresini kaydederken kullanıcısız bir doğrulama isteği atar.
        logger.info("SSV: kullanıcısız istek (konsol doğrulaması) tx=%s", transaction_id)
        return Response(status_code=status.HTTP_200_OK)
    if reward not in rewards.REWARD_TYPES or not transaction_id:
        logger.warning("SSV: bilinmeyen ödül=%r tx=%s", reward, transaction_id)
        return Response(status_code=status.HTTP_200_OK)

    result = await rewards.grant(user_id, reward, transaction_id, rewards.utc_now())
    logger.info("SSV ödül=%s sonuç=%s user_id=%s", reward, result, user_id)
    return Response(status_code=status.HTTP_200_OK)


@router.get("", response_model=RewardStateOut)
async def get_rewards(x_user_id: str | None = Header(default=None)) -> RewardStateOut:
    user_id = require_user_id(x_user_id)
    return _out(await rewards.get_state(user_id))


@router.post("/streak-freeze", response_model=RewardStateOut)
async def use_streak_freeze(payload: StreakFreezeIn, x_user_id: str | None = Header(default=None)) -> RewardStateOut:
    """Yalnız yakın geçmiş (son 2 gün) korunabilir: istemci yerel "dün"ü gönderir,
    saat dilimi farkı için UTC'ye göre 2 günlük pay var."""
    user_id = require_user_id(x_user_id)
    try:
        day = date.fromisoformat(payload.date)
    except ValueError:
        raise unprocessable("Tarih geçersiz", {"date": payload.date}) from None
    today = rewards.utc_now().date()
    if not (today - timedelta(days=2) <= day < today + timedelta(days=1)):
        raise unprocessable("Yalnız dün korunabilir", {"date": payload.date})

    state = await rewards.use_freeze(user_id, day, rewards.utc_now())
    if state is None:
        raise ApiError(status.HTTP_409_CONFLICT, "NO_STREAK_FREEZE", "Seri dondurma hakkın yok")
    return _out(state)
