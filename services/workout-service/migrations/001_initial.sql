-- workout_db ilk şema — ADR 0005: her servis kendi migration'ını taşır.
--
-- Şema, mobil taraftaki DONMUŞ veri sözleşmesinin birebir karşılığıdır:
-- core/workout/WorkoutRecord.kt  →  workouts / sets / reps / rep_form_errors

-- ---------------------------------------------------------------------------
-- exercises — egzersiz kataloğu
-- ---------------------------------------------------------------------------
-- ADR 0005 ayrı bir exercise-service'i reddetti: egzersiz tanımları neredeyse hiç
-- değişmeyen, okuma ağırlıklı statik veridir. Ayrı servis + ayrı DB + network hop'u
-- sıfır fayda üretip her antrenman sorgusuna gecikme eklerdi. Katalog burada,
-- workout-service içinde bir tablo olarak duruyor.
CREATE TABLE exercises (
    id            TEXT        PRIMARY KEY,   -- 'push_up'
    display_name  TEXT        NOT NULL,
    -- Kamera açısı bir ÜRÜN KISITI, ML problemi değil (CLAUDE.md §2).
    -- Her egzersiz hangi görüşten çekilmesi gerektiğini kendisi tanımlar.
    required_view TEXT        NOT NULL,      -- 'SIDE' | 'FRONT'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO exercises (id, display_name, required_view)
VALUES ('push_up', 'Şınav', 'SIDE');

-- ---------------------------------------------------------------------------
-- workouts — antrenman oturumu
-- ---------------------------------------------------------------------------
CREATE TABLE workouts (
    -- ★ ID İSTEMCİDE ÜRETİLİYOR ★ (WorkoutRecord.kt'de gerekçesi yazılı)
    -- Sunucu üretseydi istemci-sunucu id eşlemesi tutmak gerekirdi. İstemci UUID
    -- ürettiğinde aynı oturumu iki kez göndermek TEK kayıt üretir — ağ hatasında
    -- tekrar denemek güvenli olur (service-contract §4).
    id           UUID        PRIMARY KEY,

    -- auth_db'deki users.id ile aynı değer. FOREIGN KEY YOK: başka veritabanı
    -- (ADR 0005). Bütünlük AccountDeleted olayıyla korunuyor.
    user_id      UUID        NOT NULL,

    exercise_id  TEXT        NOT NULL REFERENCES exercises(id),

    -- Duvar saati, epoch değil TIMESTAMPTZ: kullanıcı "dün 14:30" görmek ister.
    -- Süre ölçümü sensör saatinden geliyor ve reps.duration_s'de saniye olarak
    -- duruyor — iki farklı saat, bilinçli (WorkoutRecord.kt).
    started_at   TIMESTAMPTZ NOT NULL,
    ended_at     TIMESTAMPTZ NULL,

    -- Aynı id farklı içerikle gelirse 409 dönebilmek için (service-contract §4).
    -- Gövdenin normalleştirilmiş SHA-256 özeti.
    content_hash TEXT        NOT NULL,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT workouts_time_order CHECK (ended_at IS NULL OR ended_at >= started_at)
);

-- Geçmiş listesi: en yeni üstte, cursor sayfalama (service-contract §5).
-- (user_id, started_at DESC, id DESC) sıralamanın tamamını karşılıyor.
CREATE INDEX workouts_user_started_idx ON workouts (user_id, started_at DESC, id DESC);

-- ---------------------------------------------------------------------------
-- sets — oturum içindeki setler
-- ---------------------------------------------------------------------------
CREATE TABLE sets (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workout_id   UUID        NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    -- Oturum içindeki sırası, 1'den başlar.
    set_index    SMALLINT    NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    ended_at     TIMESTAMPTZ NOT NULL,

    CONSTRAINT sets_index_positive CHECK (set_index >= 1),
    CONSTRAINT sets_time_order CHECK (ended_at >= started_at),
    -- Aynı oturumda aynı sıra numarası iki kez olamaz.
    CONSTRAINT sets_unique_index UNIQUE (workout_id, set_index)
);

CREATE INDEX sets_workout_idx ON sets (workout_id);

-- ---------------------------------------------------------------------------
-- reps — TEKRAR BAŞINA BİR SATIR
-- ---------------------------------------------------------------------------
-- ★ NEDEN TOPLAM DEĞİL, HER TEKRAR ★ (WorkoutRecord.kt)
-- Toplam sayı ham veriden her zaman hesaplanabilir; ham veri toplamdan
-- hesaplanamaz. "Form hatalarım son iki haftada azaldı mı" sorusu ancak tekrar
-- düzeyinde cevaplanır. 20 tekrarlık bir set 20 satır — maliyeti yok.
CREATE TABLE reps (
    id             UUID     PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id         UUID     NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
    rep_index      SMALLINT NOT NULL,

    -- Süreler SANİYE (REAL). Sensör saatinden türetiliyor, duvar saatinden değil.
    duration_s     REAL     NOT NULL,
    -- İniş fazı. Kontrollü iniş, form kalitesinin en iyi tek göstergesi.
    eccentric_s    REAL     NOT NULL,
    concentric_s   REAL     NOT NULL,
    -- Faz sinyalinin kat ettiği aralık [0,1].
    rom            REAL     NOT NULL,

    CONSTRAINT reps_index_positive CHECK (rep_index >= 1),
    CONSTRAINT reps_rom_range CHECK (rom >= 0 AND rom <= 1),
    CONSTRAINT reps_durations_positive
        CHECK (duration_s >= 0 AND eccentric_s >= 0 AND concentric_s >= 0),
    CONSTRAINT reps_unique_index UNIQUE (set_id, rep_index)
);

CREATE INDEX reps_set_idx ON reps (set_id);

-- ---------------------------------------------------------------------------
-- rep_form_errors — bir tekrarda tespit edilen form hataları
-- ---------------------------------------------------------------------------
-- AYRI TABLO, dizi kolonu değil: bir tekrarda birden fazla hata olabiliyor ve
-- "HIP_SAG kaç tekrarda görüldü" sorgusu ayrı tabloda indekslenebilir. Postgres
-- dizisi de mümkündü ama bu sorgu analytics-service'in ana işi olacak.
CREATE TABLE rep_form_errors (
    rep_id     UUID     NOT NULL REFERENCES reps(id) ON DELETE CASCADE,
    -- FormError enum'ı İSİM olarak taşınır, ordinal olarak değil
    -- (service-contract §7): enum sırası değişince ordinal sessizce kayar.
    error      TEXT     NOT NULL,
    -- Aynı hata aynı tekrarda iki kez kaydedilmemeli.
    PRIMARY KEY (rep_id, error)
);

CREATE INDEX rep_form_errors_error_idx ON rep_form_errors (error);

-- ---------------------------------------------------------------------------
-- outbox — auth-service ile birebir aynı desen
-- ---------------------------------------------------------------------------
-- Phase 10'da bu tablo YAZILIR ama okuyan yok: Kafka Phase 11'de (ADR 0006).
-- Şimdi kurulmasının sebebi, yazma tarafının doğru kurulmuş olması — event iş
-- verisiyle AYNI transaction'da yazılıyor. Phase 11'de yalnızca bir relay
-- eklenecek; bu servisin kodu değişmeyecek.
CREATE TABLE outbox (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type    TEXT        NOT NULL,
    topic         TEXT        NOT NULL,
    partition_key TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ NULL,
    attempts      SMALLINT    NOT NULL DEFAULT 0,
    last_error    TEXT        NULL
);

-- Kısmi indeks: relay yalnızca yayınlanmamışları arar. Yayınlanmışlar indekste
-- yer kaplamaz.
CREATE INDEX outbox_unpublished_idx ON outbox (created_at)
    WHERE published_at IS NULL;

-- ---------------------------------------------------------------------------
-- processed_events — hesap silme olayını tekrara dayanıklı tüketmek için
-- ---------------------------------------------------------------------------
CREATE TABLE processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX processed_events_processed_at_idx ON processed_events (processed_at);
