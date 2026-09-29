"""Herkese açık haftalık lig — katman, hafta ve terfi/düşme kuralları (saf mantık).

Arkadaş skor tablosundan (`routers/leaderboards.py`) FARKI: arkadaşı olmayan
yeni kullanıcı da rekabete girer. Haftalık gruplar en fazla GROUP_SIZE kişi,
aynı katmandan. Puan arkadaş tablosuyla AYNI formül (`app/scoring.py`).

★ LİG HAFTASI SABİT SAAT DİLİMİNDE ★ Grup üyeleri aynı pencereyle
karşılaştırılmalı; izleyicinin saat dilimine göre kayan hafta, iki üyenin aynı
antrenmanı farklı haftaya yazmasına yol açardı. Hedef kitle Türkiye: UTC+3.

★ SONUÇ TEMBEL HESAPLANIR ★ Hafta sonunda çalışan bir iş yok (Cloud Run'da arka
plan döngüsü yok, ADR 0020). Kullanıcı yeni haftada ilk kez lige girdiğinde
(ekranı açınca ya da ilk antrenmanında) geçen haftaki grubundaki sırası
snapshot'lardan hesaplanır ve yeni katmanı belirlenir. Snapshot'lar değişmediği
için sonuç kim ne zaman hesaplarsa hesaplasın aynı.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TIERS = ("BRONZE", "SILVER", "GOLD", "DIAMOND")
LEAGUE_OFFSET_MINUTES = 180
GROUP_SIZE = 30
PROMOTE_COUNT = 5
DEMOTE_COUNT = 5
# Küçük grupta düşme yok: 6 kişilik grupta son 5'in düşmesi cezalandırıcı olur.
MIN_GROUP_FOR_DEMOTE = 10


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def week_of(moment: datetime) -> date:
    """Lig haftasının Pazartesi'si (UTC+3)."""
    local = (moment + timedelta(minutes=LEAGUE_OFFSET_MINUTES)).date()
    return local - timedelta(days=local.weekday())


def week_end_utc(week: date) -> datetime:
    """Haftanın bittiği an (bir sonraki Pazartesi 00:00 UTC+3), UTC."""
    local_midnight = datetime.combine(week + timedelta(days=7), datetime.min.time())
    return (local_midnight - timedelta(minutes=LEAGUE_OFFSET_MINUTES)).replace(tzinfo=timezone.utc)


def tier_index(tier: str) -> int:
    return TIERS.index(tier) if tier in TIERS else 0


def zone(tier: str, rank: int, group_size: int) -> str:
    """Sıraya göre bölge: PROMOTE · DEMOTE · STAY (puan koşulu `next_tier`'da)."""
    index = tier_index(tier)
    if rank <= PROMOTE_COUNT and index < len(TIERS) - 1:
        return "PROMOTE"
    if group_size >= MIN_GROUP_FOR_DEMOTE and rank > group_size - DEMOTE_COUNT and index > 0:
        return "DEMOTE"
    return "STAY"


def next_tier(tier: str, rank: int, group_size: int, score: int) -> str:
    index = tier_index(tier)
    z = zone(tier, rank, group_size)
    if z == "PROMOTE" and score > 0:
        return TIERS[index + 1]
    if z == "DEMOTE":
        return TIERS[index - 1]
    return TIERS[index]


def after_absence(tier: str) -> str:
    """Bir haftadan fazla ara: bir katman aşağı (en alt Bronz)."""
    return TIERS[max(0, tier_index(tier) - 1)]
