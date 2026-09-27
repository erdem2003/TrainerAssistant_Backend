"""Pydantic istek/yanıt gövdeleri (ADR 0014, Faz S6)."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peer_user_id: str


class PeerOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    avatar_seed: str


class ConversationOut(BaseModel):
    id: str
    peer: PeerOut
    unread_count: int
    last_message: str | None
    last_message_from_me: bool
    last_message_redacted: bool
    last_message_at: int | None


class ConversationListOut(BaseModel):
    items: list[ConversationOut]


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    body: str = Field(min_length=1, max_length=2000)

    def content_hash(self) -> str:
        """Aynı id farklı `body` ile gelirse 409 için (workout-service'in
        idempotent yazım merdiveniyle aynı desen)."""
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    seq: int
    sender_id: str
    body: str | None
    redacted: bool
    created_at: int


class MessagePage(BaseModel):
    items: list[MessageOut]
    next_before_seq: int | None


class MarkReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    up_to_seq: int = Field(ge=0)


# --- Canlı ortak antrenman (Faz S7) -------------------------------------------
#
# ★ KALICI VERİ YOK ★ Bu uçlar `messages` tablosuna hiç dokunmaz — session_id
# rastgele üretilen bir UUID, yalnızca iki katılımcı arasında bir "kapasite
# jetonu" olarak taşınır. Doğrulama YALNIZCA `invite`'da yapılır (arkadaşlık
# kontrolü); join/progress/end bu jetonu zaten bilen tarafın gönderdiğini
# varsayar — üçüncü bir kullanıcının rastgele bir UUID'yi tahmin etmesi
# pratikte imkansız (ADR 0014'ün "kalıcı veri yok" kararının doğal sonucu:
# saklanan bir şey olmadığı için yetkiyi saklayacak bir tablo da yok).


class LiveInviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peer_user_id: str
    exercise_id: str


class LiveInviteOut(BaseModel):
    session_id: str


class LiveActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peer_user_id: str


class LiveProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peer_user_id: str
    reps: int = Field(ge=0)
