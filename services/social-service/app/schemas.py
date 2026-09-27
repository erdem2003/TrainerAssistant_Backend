"""Pydantic istek/yanit govdeleri — profil ve arkadaslik."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Kullanici adi: harf/rakam/alt cizgi, 3-24 karakter. Kucuk/buyuk harf farki
# yok — benzersizlik `lower()` uzerinden (bkz. migrations/001_initial.sql).
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,24}$")


class UsernameClaimIn(BaseModel):
    """`POST /v1/social/profiles/username` — sosyali acar, kullanici adini alir."""

    model_config = ConfigDict(extra="forbid")

    username: str
    display_name: str = Field(min_length=1, max_length=60)

    @field_validator("username")
    @classmethod
    def _valid_username(cls, v: str) -> str:
        if not _USERNAME_PATTERN.match(v):
            raise ValueError(
                "kullanıcı adı 3-24 karakter, yalnızca harf/rakam/alt çizgi olmalı"
            )
        return v


class ProfileOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    avatar_seed: str
    social_enabled: bool


class ProfileSummaryOut(BaseModel):
    """Arkadaş olmayan biri için sınırlı görünüm — yalnızca ad + avatar (ADR 0014 karar #3)."""

    user_id: str
    username: str
    display_name: str
    avatar_seed: str
    # ADR 0017 — yalnızca `/profiles/search` sonuçlarında dolu:
    # "NONE" | "PENDING_OUTGOING" | "PENDING_INCOMING" | "FRIENDS".
    # `GET /profiles/{id}` bunu hiç hesaplamıyor, None kalır.
    relationship_status: str | None = None


class ProfileSearchOut(BaseModel):
    items: list[ProfileSummaryOut]


# --- Arkadaşlık --------------------------------------------------------------


class FriendRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str


class FriendOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    avatar_seed: str
    since: int


class FriendListOut(BaseModel):
    items: list[FriendOut]


class PendingRequestOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    avatar_seed: str
    requested_at: int


class PendingRequestsOut(BaseModel):
    incoming: list[PendingRequestOut]
    outgoing: list[PendingRequestOut]


class FriendshipStatusOut(BaseModel):
    """`POST /v1/social/friendships` sonrası ne olduğunu bildirir.

    İstemci "PENDING" mi "ACCEPTED" mi olduğunu ayırt edebilmeli — karşılıklı
    istek otomatik kabul olduğunda kullanıcıya farklı bir mesaj gösterilir.
    """

    status: str


# --- Gönderi / feed (Faz S4) --------------------------------------------------


class PostIn(BaseModel):
    """İstemci kendi UUID'sini üretir (service-contract §4, idempotent yazım)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    workout_id: str
    note: str = Field(default="", max_length=500)


class PostAuthorOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    avatar_seed: str


class PostOut(BaseModel):
    id: str
    author: PostAuthorOut
    post_type: str
    # ADR 0016 — MOTIVATION gönderisinde bu altı alan hep None/0: gönderi bir
    # antrenmana bağlı değil. `has_photo=true` ise istemci
    # `GET /v1/social/posts/{id}/photo`'dan fotoğrafı çeker.
    workout_id: str | None = None
    exercise_id: str | None = None
    total_sets: int | None = None
    total_reps: int | None = None
    reps_with_errors: int | None = None
    best_set_reps: int | None = None
    has_photo: bool = False
    note: str
    like_count: int
    comment_count: int
    liked_by_me: bool
    has_clip: bool
    created_at: int


class PostPendingOut(BaseModel):
    """201 dönüşü — henüz VISIBLE değil, istemci bunu bekleme durumu olarak gösterir."""

    id: str
    status: str


class FeedPage(BaseModel):
    items: list[PostOut]
    next_cursor: str | None = None


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    body: str = Field(min_length=1, max_length=500)
    # Faz S13, "yoruma yorum" — doluysa bu bir YANIT, üst yorumun altına
    # yazılır. Boşsa gönderiye doğrudan (üst seviye) yorum.
    parent_comment_id: str | None = None


class CommentOut(BaseModel):
    id: str
    post_id: str
    author: PostAuthorOut
    body: str
    parent_comment_id: str | None = None
    # Yalnızca üst seviye yorumlarda anlamlı — yanıtın yanıtı yok (TEK
    # SEVİYE, bkz. migration 008), bu yüzden bir yanıt satırında hep 0.
    reply_count: int = 0
    created_at: int


class CommentPage(BaseModel):
    items: list[CommentOut]
    next_cursor: str | None = None


# --- Haftalık skor tablosu (Faz S5) ------------------------------------------


class LeaderboardEntryOut(BaseModel):
    rank: int
    user_id: str
    username: str
    display_name: str
    avatar_seed: str
    is_me: bool
    score: int
    total_reps: int
    clean_reps: int
    total_sets: int
    active_days: int
    rep_points: int
    clean_bonus_points: int
    consistency_points: int


class LeaderboardOut(BaseModel):
    week_start: str
    items: list[LeaderboardEntryOut]


# --- Bildirimler (Faz S8) ------------------------------------------------------


class NotificationActorOut(BaseModel):
    """Aktör profili silinmiş olabilir — tüm alanlar `None` olabilir, S10'un
    tam sertleştirmesine kadar geçici bir "Silinmiş kullanıcı" gösterimi."""

    user_id: str
    username: str | None
    display_name: str | None
    avatar_seed: str | None


class NotificationOut(BaseModel):
    id: str
    type: str
    actor: NotificationActorOut
    subject_id: str
    created_at: int
    read: bool


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread_count: int
    next_cursor: str | None = None


# --- Meydan okuma + kudos (Faz S9) ---------------------------------------------


class ChallengeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = Field(min_length=1, max_length=100)
    exercise_id: str | None = None
    target_reps: int = Field(gt=0)
    starts_at: int
    ends_at: int


class ChallengeParticipantOut(BaseModel):
    user_id: str
    username: str | None
    display_name: str | None
    avatar_seed: str | None
    progress_reps: int
    is_me: bool


class ChallengeOut(BaseModel):
    id: str
    creator_id: str
    title: str
    exercise_id: str | None
    target_reps: int
    starts_at: int
    ends_at: int
    participants: list[ChallengeParticipantOut]


class ChallengeListOut(BaseModel):
    items: list[ChallengeOut]


class KudosOut(BaseModel):
    workout_id: str
    kudos_count: int
    given_by_me: bool


# --- İskelet klibi paylaşımı (ADR 0015, Faz S11) -------------------------------
#
# ★ SUNUCU KARE İÇERİĞİNİ DOĞRULAMAZ ★ `landmarks` sözlüğünün anahtarları
# (`LandmarkType` isimleri) ve `[x, y, likelihood]` üçlüsü mobil `:core`
# modülünün iç temsili — sunucu bunu YORUMLAMIYOR, yalnızca boyut/sayı
# sınırlarını kontrol edip saklıyor (bkz. `app/repo/clips.py` KDoc).

_MAX_FRAMES = 450  # RepFrameBuffer.DEFAULT_MAX_FRAMES ile aynı (core, Kotlin)
_MAX_LANDMARKS_PER_FRAME = 40  # 17 gerçek nokta + pay


class ClipFrameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: int  # timestampNanos
    landmarks: dict[str, list[float]] = Field(max_length=_MAX_LANDMARKS_PER_FRAME)

    @field_validator("landmarks")
    @classmethod
    def _valid_landmarks(cls, v: dict[str, list[float]]) -> dict[str, list[float]]:
        for name, triplet in v.items():
            if len(triplet) != 3:
                raise ValueError(f"landmark '{name}' [x, y, likelihood] üçlüsü olmalı")
        return v


class ClipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frames: list[ClipFrameIn] = Field(min_length=1, max_length=_MAX_FRAMES)
    form_errors: list[str] = Field(default_factory=list, max_length=10)
    # `PoseOverlay`'in `ViewTransform.fitCenter`'ı koordinatları bu boyuta göre
    # ölçekliyor (mobil `pose/PoseOverlay.kt`) — kaydedilmezse oynatıcı
    # skeleton'ı yanlış oranla çizer. Kamera çözünürlüğü bir klip boyunca
    # sabit, bu yüzden üst seviyede tek değer (kare başına değil).
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)


class ClipOut(BaseModel):
    post_id: str
    frames: list[ClipFrameIn]
    form_errors: list[str]
    frame_count: int
    image_width: int
    image_height: int
