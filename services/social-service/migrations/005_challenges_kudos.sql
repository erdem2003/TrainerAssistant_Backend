-- Meydan okuma + kudos (ADR 0014, Faz S9).
--
-- ★ İLERLEME SAKLANMIYOR ★ `challenges`/`challenge_participants` yalnızca
-- HEDEFİ ve KİMİN katıldığını tutar. İlerleme çubuğu her sorguda
-- `workout_snapshots`'tan `[starts_at, ends_at)` aralığında toplanır (ADR
-- 0012'nin genel ilkesi, `workout_snapshots` ile aynı disiplin).
CREATE TABLE challenges (
    id           UUID        PRIMARY KEY,
    creator_id   UUID        NOT NULL,
    title        TEXT        NOT NULL,
    -- NULL = herhangi bir egzersiz sayılır (toplam tekrar). Dolu ise yalnızca
    -- o egzersizin tekrarları hedefe katkı sağlar.
    exercise_id  TEXT,
    target_reps  INTEGER     NOT NULL CHECK (target_reps > 0),
    starts_at    TIMESTAMPTZ NOT NULL,
    ends_at      TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE challenge_participants (
    challenge_id UUID        NOT NULL REFERENCES challenges (id) ON DELETE CASCADE,
    user_id      UUID        NOT NULL,
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (challenge_id, user_id)
);

CREATE INDEX challenge_participants_user_idx ON challenge_participants (user_id);

-- Kudos: `post_likes`'ın gönderi GEREKTİRMEYEN hâli — bir arkadaşın DOĞRUDAN
-- antrenmanına (paylaşılmış bir gönderisi olsun olmasın) tek dokunuş. Sayaç
-- yok, `post_likes` ile aynı gerekçe (ADR 0012, COUNT sorgu anında).
CREATE TABLE workout_kudos (
    workout_id UUID        NOT NULL,
    giver_id   UUID        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workout_id, giver_id)
);

-- Bildirim tipine WORKOUT_KUDOS eklenir (004'teki CHECK genişletiliyor).
ALTER TABLE notifications DROP CONSTRAINT notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check
    CHECK (type IN ('FRIEND_REQUEST', 'FRIEND_ACCEPTED', 'POST_LIKED', 'POST_COMMENTED', 'WORKOUT_KUDOS'));
