"""Kullanicinin YEREL gunu ile UTC arasindaki cevrim.

`analytics-service/app/localday.py`'nin birebir kopyasi — servisler kod
paylasmiyor (ADR 0005), ama mantik identik olmali: aksi halde ayni hafta
sinirini iki servis farkli hesaplar ve "haftalik skor tablom yanlis" gibi
SESSIZ bir hataya yol acar.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.errors import unprocessable

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
