-- Uyku takibi — ADR 0010'un ikinci tablosu.
--
-- `water_logs` ile AYNI ŞEKİL: kullanıcı + tarih + bir sayı. ADR üçünün de bu
-- şekle sahip olduğunu söylüyordu; desen birebir tekrarlanıyor.

-- ---------------------------------------------------------------------------
-- sleep_logs — gecelik uyku süresi
-- ---------------------------------------------------------------------------
CREATE TABLE sleep_logs (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- auth_db'deki users.id ile aynı değer. FOREIGN KEY YOK: başka veritabanı
    -- (ADR 0005). Bütünlük AccountDeleted olayıyla korunuyor.
    user_id    UUID        NOT NULL,

    -- ★ UYANILAN GÜN ★
    -- Bir uyku iki takvim gününe yayılıyor: 23:30'da yatıp 07:00'de kalkmak
    -- hangi güne ait? UYANILAN gün seçildi çünkü kullanıcı sabah kaydediyor ve
    -- "bugün 7 saat uyudum" derken kalktığı günü kastediyor. Yatılan günü
    -- seçmek, gece yarısından sonra yatan birinin uykusunu bir sonraki güne
    -- yazardı ve "dün hiç uyumamışım" gibi görünürdü.
    log_date   DATE        NOT NULL,

    -- DAKİKA, saat değil: 7,5 saat ondalık bir sayı ve kayan nokta yuvarlama
    -- hatası girerdi. Dakika tamsayı ve gösterimde "7 sa 30 dk"ya çevriliyor.
    minutes    INTEGER     NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- 0 GEÇERLİ: kullanıcı yanlış girdiğini sıfıra çekebilmeli.
    -- Üst sınır 24 saat — fazlası veri girişi hatası.
    CONSTRAINT sleep_logs_minutes_range CHECK (minutes >= 0 AND minutes <= 1440),

    -- Gece başına tek satır.
    CONSTRAINT sleep_logs_unique_day UNIQUE (user_id, log_date)
);

CREATE INDEX sleep_logs_user_date_idx ON sleep_logs (user_id, log_date);
