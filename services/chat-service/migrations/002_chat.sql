-- Birebir mesajlaşma (ADR 0014, Faz S6).
--
-- ★ SEQ, SUNUCUDA ATANAN TAM SAYI ★ İstemci id'si (`messages.id`) idempotent
-- yazım için (service-contract §4), `seq` ise SIRALAMA için — istemci saati
-- güvenilir değil, iki mesaj aynı milisaniyede gelebilir. `conversations.
-- next_seq` her gönderimde `UPDATE ... RETURNING next_seq - 1` ile atomik
-- artırılıyor (app/repo/messages.py).
CREATE TABLE conversations (
    id         UUID        PRIMARY KEY,
    user_low   UUID        NOT NULL,
    user_high  UUID        NOT NULL,
    next_seq   INTEGER     NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_low, user_high),
    CHECK (user_low < user_high)
);

-- ★ OKUNDU BİLGİSİ TEK SATIR, GREATEST İLE ★ Her mesaj için ayrı bir "okundu"
-- satırı YOK — `last_read_seq` üzerinde `GREATEST(last_read_seq, $2)` ile
-- güncelleniyor: sıra dışı/tekrar eden bir "okundu" isteği asla geri
-- SARMIYOR (idempotent, sıra-bağımsız — app/repo/conversations.py).
--
-- `left_at`, Faz S10'un hesap silme akışında kullanılacak: kullanıcı
-- silindiğinde konuşmadan "ayrılmış" sayılır ama satır KALIR — mesaj
-- geçmişi ve `last_read_seq` kaybolmamalı.
CREATE TABLE conversation_participants (
    conversation_id UUID        NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    user_id          UUID        NOT NULL,
    last_read_seq     INTEGER     NOT NULL DEFAULT 0,
    last_read_at       TIMESTAMPTZ,
    left_at             TIMESTAMPTZ,
    PRIMARY KEY (conversation_id, user_id)
);

CREATE INDEX conversation_participants_user_idx ON conversation_participants (user_id);

-- `content_hash`, workout-service'in idempotent yazım merdiveninin (201/200/409)
-- aynısı: aynı `id` farklı `content_hash` ile gelirse 409, aynısıyla gelirse
-- 200 + mevcut satır. `redacted_at` Faz S10'un silme-yerine-redaksiyon
-- kuralı için — mesaj SİLİNMİYOR, `body` NULL'lanıp `redacted_at` damgalanıyor
-- (yapısal alanlar — seq, created_at — kalıyor, ADR 0014 Sonuçlar).
CREATE TABLE messages (
    id               UUID        PRIMARY KEY,
    conversation_id  UUID        NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    seq               INTEGER     NOT NULL,
    sender_id          UUID        NOT NULL,
    body                TEXT,
    content_hash         TEXT        NOT NULL,
    redacted_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, seq)
);

CREATE INDEX messages_conversation_created_idx ON messages (conversation_id, created_at);
