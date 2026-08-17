"""Pydantic istek/yanit govdeleri — su takibi."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Tek seferde eklenebilecek en fazla miktar. Gunluk ust sinir (20 L) veritabani
# kisitinda; buradaki sinir tek bir dokunusun makul olcusu.
_MAX_SINGLE_ADD_ML = 5000


class WaterAddIn(BaseModel):
    """`POST /v1/water` — gunun toplamina EKLER."""

    model_config = ConfigDict(extra="forbid")

    amount_ml: int = Field(ge=1, le=_MAX_SINGLE_ADD_ML)


class WaterSetIn(BaseModel):
    """`PUT /v1/water` — gunun toplamini DOGRUDAN ayarlar.

    Ayri bir uc, cunku "ekle" ile "duzelt" farkli niyetler ve ayni ucla
    ifade edilirse istemcinin bir bayrak gondermesi gerekirdi. 0 GECERLI:
    kullanici yanlislikla ekledigini sifirlayabilmeli.
    """

    model_config = ConfigDict(extra="forbid")

    amount_ml: int = Field(ge=0, le=20000)


class WaterDayOut(BaseModel):
    date: str
    amount_ml: int


class WaterRangeOut(BaseModel):
    """Yalnizca KAYDI OLAN gunler doner; bos gunler yok.

    Araliktaki her gunu sifirla doldurmak yaniti sisirirdi ve istemci grafigi
    cizerken tarih eksenini zaten kendisi kuruyor.
    """

    days: list[WaterDayOut]


# --- Uyku -------------------------------------------------------------------

class SleepSetIn(BaseModel):
    """`PUT /v1/sleep` — gecenin suresini ayarlar.

    ★ SU'DAN FARKLI OLARAK "EKLE" UCU YOK ★
    Uyku birikimli degil, tek bir olcum. Ekleme ucu olsaydi ayni geceyi iki kez
    kaydetmek 14 saat uretirdi.

    0 GECERLI ama "hic uyumadim" demek; kaydi tamamen kaldirmak icin
    `DELETE /v1/sleep` var. Ikisi ortalama hesabinda farkli davraniyor.
    """

    model_config = ConfigDict(extra="forbid")

    minutes: int = Field(ge=0, le=1440)


class SleepDayOut(BaseModel):
    date: str
    # `null` = o gun icin kayit YOK ("girmedim"), 0 = "hic uyumadim".
    minutes: int | None


class SleepRangeOut(BaseModel):
    days: list[SleepDayOut]
