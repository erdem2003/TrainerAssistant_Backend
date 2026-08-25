-- B6 (vücut ölçüsü trendi) ve D1 (kişisel kalibrasyon) için iki yeni tablo.
-- İkisi de user-service'e ait: profilin bir uzantısı, ayrı servis gerektirmiyor.

-- ---------------------------------------------------------------------------
-- body_measurements — zaman içindeki vücut ölçüleri
-- ---------------------------------------------------------------------------
-- `profiles.weight_kg` ANLIK deger; burasi ZAMAN SERISI. Ikisi ayni alani
-- farkli amacla tasiyor: profil "su an ne" sorusuna, bu tablo "nasil
-- degisiyor" sorusuna cevap veriyor. Senkronizasyonlari GEREKMIYOR — kullanici
-- yeni bir olcum eklediginde istemci profili de guncelleyebilir ama bu tablo
-- onun turevi degil, bagimsiz bir kayit.
CREATE TABLE body_measurements (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL,

    -- water_logs ile ayni desen: kullanicinin YEREL gunu, TIMESTAMPTZ degil.
    measured_date  DATE        NOT NULL,

    -- Ucu de opsiyonel: kullanici sadece kiloyu girip bel/kol'u atlayabilir.
    -- Ayri tablolar yerine tek satirda nullable kolonlar secildi cunku uc
    -- deger de AYNI ANDA girilen tek bir olcumun parcasi.
    weight_kg      REAL        NULL,
    waist_cm       REAL        NULL,
    arm_cm         REAL        NULL,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT body_measurements_weight_range
        CHECK (weight_kg IS NULL OR (weight_kg >= 20 AND weight_kg <= 350)),
    CONSTRAINT body_measurements_waist_range
        CHECK (waist_cm IS NULL OR (waist_cm >= 30 AND waist_cm <= 250)),
    CONSTRAINT body_measurements_arm_range
        CHECK (arm_cm IS NULL OR (arm_cm >= 10 AND arm_cm <= 80)),

    -- Gun basina tek satir — su takibinin izledigi ayni karar.
    CONSTRAINT body_measurements_unique_day UNIQUE (user_id, measured_date)
);

CREATE INDEX body_measurements_user_date_idx
    ON body_measurements (user_id, measured_date);

-- ---------------------------------------------------------------------------
-- calibration_profiles — kişisel eşik ölçümü (D1)
-- ---------------------------------------------------------------------------
-- ★ YALNIZCA SAKLAMA, CANLI FSM'E BAĞLANMIYOR ★
-- Bu tablo ölçülen değerleri tutar. Bir eşiği DEĞİŞTİRMEK `cv-engineer`
-- alanı (CLAUDE.md §6) — android-engineer tek taraflı eşik bağlayamaz. Bu
-- yüzden şimdilik yalnızca "ölçüldü, işte değerler" bilgisini taşıyor;
-- FSM'e canlı bağlanması ayrı bir kararla yapılacak.
CREATE TABLE calibration_profiles (
    user_id       UUID        NOT NULL,
    exercise_id   TEXT        NOT NULL,

    -- Kaç tekrar üzerinden ölçüldüğü — 5'in altı "kalibrasyon" sayılmaz,
    -- istemci bunu göstermeden önce kontrol eder.
    sample_count  SMALLINT    NOT NULL,

    -- Ölçülen ham değerler: açı min/maks, gövde oranı vb. Şema egzersize göre
    -- değişir (pose-math feature adlarıyla anahtarlanır) — sabit kolon seti
    -- yerine JSONB, yeni egzersiz eklenince migration gerektirmesin diye.
    measured_values JSONB      NOT NULL,

    calibrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, exercise_id)
);
