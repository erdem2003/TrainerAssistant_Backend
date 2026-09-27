"""GET/POST/PUT /v1/water — gunluk su tuketimi (ADR 0010)."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Header, Query

from app.errors import unprocessable
from app.identity import require_user_id
from app.repo import water
from app.schemas import WaterAddIn, WaterDayOut, WaterRangeOut, WaterSetIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["water"])

# Istatistik ekraninin en genis gorunumu bir ay; 400 gun fazlasiyla pay birakiyor
# ve tek istekte butun gecmisi taramayi engelliyor.
_MAX_RANGE_DAYS = 400


def _parse_date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise unprocessable(
            "Tarih YYYY-AA-GG biçiminde olmalı", {"field": field}
        ) from None


@router.get("/water", response_model=WaterDayOut)
async def get_water(
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
) -> WaterDayOut:
    """Bir günün su toplamı. Kayıt yoksa 404 DEĞİL, sıfır döner.

    404 dönmek istemciyi "kayıt var mı" ve "ne kadar" diye iki ayrı duruma
    zorlardı; oysa "hiç içmemiş" ile "0 ml içmiş" aynı şey.
    """
    user_id = require_user_id(x_user_id)
    target = _parse_date(day, "date")

    row = await water.fetch_day(user_id, target)

    return WaterDayOut(
        date=target.isoformat(),
        amount_ml=row.amount_ml if row else 0,
    )


@router.post("/water", response_model=WaterDayOut)
async def add_water(
    payload: WaterAddIn,
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
) -> WaterDayOut:
    """Günün toplamına ekler.

    ★ BU UÇ IDEMPOTENT DEĞİL VE OLAMAZ ★
    "200 ml daha içtim" doğası gereği birikimli; aynı isteği iki kez göndermek
    400 ml demek ve bu DOĞRU davranış. Ağ hatasında istemci tekrar denerse
    fazla sayabilir — bu yüzden düzeltme yolu var (`PUT /v1/water`), kullanıcı
    sayıyı elle geri çekebiliyor.

    Alternatif, istemcinin istek başına bir id üretip sunucunun tekrarları
    yutması olurdu (antrenman yükleme deseni). Su için bunun maliyeti faydasını
    aşıyor: yanlış sayı iki dokunuşla düzeltiliyor, antrenman kaydı ise
    düzeltilemez.
    """
    user_id = require_user_id(x_user_id)
    target = _parse_date(day, "date")

    row = await water.add(user_id, target, payload.amount_ml)

    logger.info(
        "su eklendi user_id=%s gün=%s eklenen=%d toplam=%d",
        user_id, target, payload.amount_ml, row.amount_ml,
    )
    return WaterDayOut(date=row.log_date.isoformat(), amount_ml=row.amount_ml)


@router.put("/water", response_model=WaterDayOut)
async def set_water(
    payload: WaterSetIn,
    x_user_id: str | None = Header(default=None),
    day: str = Query(alias="date"),
) -> WaterDayOut:
    """Günün toplamını doğrudan ayarlar. Idempotent."""
    user_id = require_user_id(x_user_id)
    target = _parse_date(day, "date")

    row = await water.set_amount(user_id, target, payload.amount_ml)

    return WaterDayOut(date=row.log_date.isoformat(), amount_ml=row.amount_ml)


@router.get("/water/range", response_model=WaterRangeOut)
async def get_water_range(
    x_user_id: str | None = Header(default=None),
    start_day: str = Query(alias="from"),
    end_day: str = Query(alias="to"),
) -> WaterRangeOut:
    """Aralıktaki günlerin su toplamları — İstatistik grafiği için."""
    user_id = require_user_id(x_user_id)
    first = _parse_date(start_day, "from")
    last = _parse_date(end_day, "to")

    if last < first:
        raise unprocessable("Bitiş tarihi başlangıçtan önce olamaz")
    if (last - first).days + 1 > _MAX_RANGE_DAYS:
        raise unprocessable("Aralık çok geniş", {"max_days": _MAX_RANGE_DAYS})

    rows = await water.fetch_range(user_id, first, last)

    return WaterRangeOut(
        days=[
            WaterDayOut(date=row.log_date.isoformat(), amount_ml=row.amount_ml)
            for row in rows
        ]
    )
