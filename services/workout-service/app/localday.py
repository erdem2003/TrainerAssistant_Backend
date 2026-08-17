"""Kullanicinin YEREL gunu ile UTC arasindaki cevrim.

★ NEDEN AYRI MODUL ★
Bu mantigi iki router paylasiyor (`plan`, `stats`) ve ileride analytics de
paylasacak. Kopyalanmis iki surum zamanla ayrisir; ayrismanin belirtisi de
"antrenmanim yanlis gune yazildi" gibi SESSIZ bir hata olur — kimse hata mesaji
gormez, yalnizca sayilar tutmaz.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.errors import unprocessable

# Saat dilimi farkinin makul siniri: UTC-14 .. UTC+14 (dakika).
# Disina cikan deger istemci hatasidir ve gun sinirini anlamsiz yere kaydirir.
MAX_OFFSET_MINUTES = 14 * 60


def parse_date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise unprocessable(
            "Tarih YYYY-AA-GG biçiminde olmalı", {"field": field}
        ) from None


def check_offset(offset_minutes: int) -> int:
    if abs(offset_minutes) > MAX_OFFSET_MINUTES:
        raise unprocessable(
            "Saat dilimi farkı geçersiz", {"tz_offset": offset_minutes}
        )
    return offset_minutes


def day_bounds(day: date, offset_minutes: int) -> tuple[datetime, datetime]:
    """Kullanicinin YEREL gununu UTC yarim acik araliga cevirir.

    ★ BU FONKSIYON ISIN KALBI ★
    `workouts.started_at` UTC. Kullanicinin "17 Agustos"u UTC+3'te
    16 Agustos 21:00 UTC'de baslar. Cevrim yapilmazsa gece yarisindan sonra
    yapilan antrenmanlar bir onceki gune yazilir ve kullanici "ben bugun
    yaptim ama sayilmadi" der.

    Yarim acik aralik `[start, end)`: gun sonundaki tam saniye bir sonraki
    gune ait. Kapali aralik olsaydi gece yarisinda baslayan bir antrenman iki
    gunde birden sayilirdi.
    """
    offset = timedelta(minutes=offset_minutes)
    local_midnight = datetime.combine(day, datetime.min.time())
    start = (local_midnight - offset).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def range_bounds(
    first: date, last: date, offset_minutes: int
) -> tuple[datetime, datetime]:
    """Kapali gun araligini `[first 00:00, last+1 00:00)` UTC araligina cevirir."""
    start, _ = day_bounds(first, offset_minutes)
    _, end = day_bounds(last, offset_minutes)
    return start, end
