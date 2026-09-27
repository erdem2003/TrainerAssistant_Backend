-- Antrenman kartı gönderisi + beğeni + yorum (ADR 0014, Faz S4).
--
-- ★ ANTRENMAN İSTATİSTİKLERİ BURADA TEKRARLANMIYOR ★ `posts` yalnızca
-- "kim, hangi antrenmanı, ne notla paylaştı" tutuyor. Tekrar/set/hata sayıları
-- `workout_snapshots`'tan `workout_id` ile JOIN edilir (app/repo/posts.py) —
-- iki yerde aynı sayıyı tutmak, biri güncellenip diğeri unutulduğunda
-- sessizce çelişen sayılar üretirdi (ADR 0012'nin genel ilkesi).
--
-- ★ DURUM MAKINESI: PENDING_SNAPSHOT -> VISIBLE ★ Antrenman biter bitmez
-- istemci paylaşım isteği atabilir ama `workout_snapshots` projeksiyonu
-- Kafka'dan birkaç saniye gecikmeli gelir (Faz S3). Gönderi PENDING_SNAPSHOT
-- olarak hemen 201 döner; ya aynı transaction'da snapshot zaten varsa hızlı
-- yoldan VISIBLE'a geçer, ya da `app/worker/workout_consumer.py` snapshot'ı
-- yazınca UPDATE ile VISIBLE'a taşır (app/repo/posts.py: promote_pending).
CREATE TABLE posts (
    id          UUID        PRIMARY KEY,
    author_id   UUID        NOT NULL,
    workout_id  UUID        NOT NULL,
    note        TEXT        NOT NULL DEFAULT '',
    status      TEXT        NOT NULL DEFAULT 'PENDING_SNAPSHOT'
                CHECK (status IN ('PENDING_SNAPSHOT', 'VISIBLE')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Aynı workout_id ile iki kez paylaşım açılamaz (yazarın kendi antrenmanı
-- için) — idempotent yazımın doğal anahtarı zaten `id` (istemci UUID'si),
-- ama bu ikinci bir yanlış kullanım sınıfını (aynı antrenmanı iki farklı
-- post id'siyle paylaşmak) da engelliyor.
CREATE UNIQUE INDEX posts_author_workout_idx ON posts (author_id, workout_id);

-- Feed sorgusu: arkadaş kümesi + VISIBLE + created_at DESC sayfalama.
CREATE INDEX posts_author_created_idx ON posts (author_id, created_at DESC) WHERE status = 'VISIBLE';

-- 15 dakika sonra hâlâ PENDING_SNAPSHOT olan satırlar süpürücüyle silinir
-- (uydurma workout_id — app/worker/workout_consumer.py'deki sweep_stale_posts).
CREATE INDEX posts_pending_created_idx ON posts (created_at) WHERE status = 'PENDING_SNAPSHOT';

CREATE TABLE post_likes (
    post_id    UUID        NOT NULL REFERENCES posts (id) ON DELETE CASCADE,
    user_id    UUID        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, user_id)
);

CREATE TABLE post_comments (
    id         UUID        PRIMARY KEY,
    post_id    UUID        NOT NULL REFERENCES posts (id) ON DELETE CASCADE,
    author_id  UUID        NOT NULL,
    body       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX post_comments_post_created_idx ON post_comments (post_id, created_at);
