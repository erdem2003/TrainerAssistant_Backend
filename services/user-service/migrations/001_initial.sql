-- user_db ilk şema — ADR 0005: her servis kendi migration'ını taşır.
--
-- İKİ TABLO VAR VE İKİSİ DE GEREKLİ:
--   profiles          — bu servisin sahip olduğu tek veri
--   processed_events  — idempotent consumer (service-contract §8)

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------
-- user_id BİRİNCİL ANAHTAR ve auth-service'in ürettiği UUID ile AYNI.
-- Ayrı bir profil id'si üretilmiyor: iki id tutmak, ikisini eşleyen bir tablo
-- ve "hangisi hangisiydi" sorusunu getirir. Kullanıcı zaten tek.
--
-- FOREIGN KEY YOK — auth_db BAŞKA BİR VERİTABANI. ADR 0005'in "hiçbir servis
-- başkasının veritabanına dokunmaz" kuralı, referans bütünlüğünün veritabanı
-- seviyesinde kurulamayacağı anlamına da geliyor. Bütünlük event akışıyla
-- (AccountDeleted) sağlanıyor; bu, dağıtık mimarinin kabul edilmiş bedeli.
CREATE TABLE profiles (
    user_id                 UUID        PRIMARY KEY,

    -- FEMALE | MALE | UNSPECIFIED. Kullanıcı belirtmek zorunda değil.
    sex                     TEXT        NULL,

    -- YAŞ DEĞİL DOĞUM TARİHİ: yaş her yıl bayatlar, tarih bayatlamaz.
    birth_date              DATE        NULL,

    -- KANONİK BİRİM — her zaman kg ve cm. Kullanıcının lb/inch tercihi
    -- `unit_system`'de ayrı duruyor ve yalnızca GÖSTERİMİ etkiler. Sayıyı
    -- kullanıcının seçtiği birimde saklayıp yanına bayrak koymak, her tüketiciye
    -- dönüşüm yükler ve biri mutlaka unutur.
    weight_kg               REAL        NULL,
    height_cm               REAL        NULL,

    -- MUSCLE_GAIN | FAT_LOSS_HIIT | FAT_LOSS_CARDIO | FUNCTIONAL
    goal                    TEXT        NULL,

    unit_system             TEXT        NOT NULL DEFAULT 'METRIC',

    -- core/health/HealthMetrics.kt: DEFAULT_DAILY_GOAL = 20
    daily_goal_reps         INTEGER     NOT NULL DEFAULT 20,

    -- Onboarding'in gösterilip gösterilmeyeceğini alanların NULL olup
    -- olmamasından çıkarmak kırılgan olurdu: kullanıcı kilosunu silerse
    -- onboarding tekrar açılırdı. Açık işaret daha dürüst.
    onboarding_completed_at TIMESTAMPTZ NULL,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Enum değerleri veritabanı seviyesinde de sınırlanıyor. Pydantic zaten
    -- doğruluyor ama tek savunma hattı bırakmak, ileride başka bir yazma yolu
    -- (migration, elle düzeltme, yeni bir router) eklendiğinde sessizce
    -- bozulmaya açık kalırdı.
    CONSTRAINT profiles_sex_valid
        CHECK (sex IS NULL OR sex IN ('FEMALE', 'MALE', 'UNSPECIFIED')),
    CONSTRAINT profiles_goal_valid
        CHECK (goal IS NULL OR goal IN
               ('MUSCLE_GAIN', 'FAT_LOSS_HIIT', 'FAT_LOSS_CARDIO', 'FUNCTIONAL')),
    CONSTRAINT profiles_unit_system_valid
        CHECK (unit_system IN ('METRIC', 'IMPERIAL')),

    -- Fiziksel olarak imkânsız değerler. İnsan boyu rekoru 272 cm, en ağır
    -- kayıtlı insan 635 kg; sınırlar onların dışında değil, makul kullanım
    -- aralığında tutuldu — amaç veri kalitesi, tıbbi doğruluk değil.
    CONSTRAINT profiles_weight_range
        CHECK (weight_kg IS NULL OR (weight_kg >= 20 AND weight_kg <= 350)),
    CONSTRAINT profiles_height_range
        CHECK (height_cm IS NULL OR (height_cm >= 80 AND height_cm <= 260)),
    CONSTRAINT profiles_daily_goal_range
        CHECK (daily_goal_reps >= 1 AND daily_goal_reps <= 1000)
);

-- ---------------------------------------------------------------------------
-- processed_events
-- ---------------------------------------------------------------------------
-- Event teslimi AT-LEAST-ONCE (ADR 0006): aynı event iki kez gelebilir.
-- Silme işlemi kendiliğinden idempotent olsa da (silinmiş satırı tekrar silmek
-- zararsız), bu tablo deseni Phase 11'de Kafka geldiğinde zararsız OLMAYAN
-- event'ler için hazır olmalı. Şimdi kurmak, sonra her consumer'a ayrı ayrı
-- eklemekten ucuz.
CREATE TABLE processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Eski kayıtların temizliği için: sonsuza kadar büyümemeli.
CREATE INDEX processed_events_processed_at_idx ON processed_events (processed_at);
