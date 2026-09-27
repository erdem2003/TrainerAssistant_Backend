-- Sosyal kimlik + arkadaslik (ADR 0014, Faz S2).
--
-- ★ KULLANICI ADI BURADA, `user_db`'DE DEGIL ★
-- ADR 0010'un ayni gerekcesi: `user_db.profiles` durgun vucut olcusu tutuyor
-- (yas/kilo/boy/hedef); kullanici adi, gorunen ad ve avatar sosyal kimligin
-- kendisi ve yalnizca bu servisin sordugu sorulara cevap veriyor. Sonucu:
-- benzersizlik tek bir UNIQUE kisitiyla saglaniyor, outbox/relay/topic/
-- projeksiyon zinciri hic gerekmiyor.
CREATE TABLE social_profiles (
    user_id        UUID        PRIMARY KEY,
    username       TEXT        NOT NULL,
    display_name   TEXT        NOT NULL,
    avatar_seed    TEXT        NOT NULL,
    social_enabled BOOLEAN     NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Kucuk harfe indirgenmis benzersizlik: "Ahmet" ve "ahmet" ayni kullanici
-- adidir. Aramanin da ayni indirgemeyi kullanmasi gerekir (bkz. repo/profiles.py).
CREATE UNIQUE INDEX social_profiles_username_lower_idx
    ON social_profiles (lower(username));

-- Yalnizca sosyali acmis kullanicilar arama sonucunda cikar (opt-in, ADR 0014
-- karar #1). Kismi indeks: kapali kullanicilar bu indekste hic yer almiyor.
CREATE INDEX social_profiles_enabled_search_idx
    ON social_profiles (lower(username))
    WHERE social_enabled;

-- ★ ARKADASLIK TEK KANONIK SATIRLA TEMSIL EDILIYOR ★
-- Istek/kabul icin iki ayri satir DEGIL: (user_low, user_high) cifti (kucuk
-- id once), tek `status` alani. Karsilikli istek atilirsa (INSERT ...
-- ON CONFLICT) cakisma PENDING satirina duser ve uygulama katmani onu
-- otomatik ACCEPTED'e cevirir — iki taraf da zaten istemis demektir
-- (ADR 0014, Sonuclar). Engelleme de ayni satirin bir durumu.
CREATE TABLE friendships (
    user_low     UUID        NOT NULL,
    user_high    UUID        NOT NULL,
    status       TEXT        NOT NULL
                 CHECK (status IN ('PENDING', 'ACCEPTED', 'BLOCKED')),
    requested_by UUID        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_low, user_high),
    CHECK (user_low < user_high),
    CHECK (requested_by IN (user_low, user_high))
);

-- "Bana gelen bekleyen istekler" ve "arkadas listem" sorgulari her iki
-- kolonu da tek basina arayabilmeli (ADR 0005'in kanonik-cift onerisinin
-- bedeli: OR yerine iki indeks).
CREATE INDEX friendships_user_low_idx ON friendships (user_low, status);
CREATE INDEX friendships_user_high_idx ON friendships (user_high, status);

-- Kullanici adi serbest birakildiginda 30 gun yeniden alinamaz — serbest
-- birakilsaydi yeni bir hesap eski sosyal kimligi (arkadaş listesindeki
-- gorunumu) aninda devralabilirdi (ADR 0014, Sonuclar).
CREATE TABLE retired_usernames (
    username_lower TEXT        PRIMARY KEY,
    retired_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hesap silme fanout'unun tombstone'u (Faz S10) — `workout.session`
-- tuketicisi (Faz S3) silinen kullanicinin gecikmeli event'ini reddetmek
-- icin bu tabloyu kontrol edecek.
CREATE TABLE deleted_users (
    user_id    UUID        PRIMARY KEY,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent silme (workout-service/health-service ile ayni desen).
CREATE TABLE processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
