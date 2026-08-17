-- health_db ilk şema — ADR 0010: günlük sağlık kaydı için ayrı servis.
--
-- ★ ADR 0010'DAN BİLİNÇLİ SAPMA ★
-- ADR üç tablo tanımlıyor: `sleep_logs`, `water_logs`, `weight_logs`. Burada
-- yalnızca `water_logs` açılıyor. Sebep CLAUDE.md §5: doldurulmayacak iskelet
-- kurmamak. Su takibi İstatistik ekranında GERÇEKTEN kullanılıyor; uyku ve kilo
-- geçmişinin bugün hiçbir tüketicisi yok ve boş tablolar "yapıldı" izlenimi
-- verirdi.
--
-- ADR'nin SINIR kararı (bu veri kendi servisine ait) aynen uygulanıyor; yalnızca
-- tabloların hepsi bir kerede açılmıyor. Diğer ikisi eklenirken bu dosyanın
-- deseni birebir tekrarlanır — üçü de aynı şekle sahip: kullanıcı + tarih + sayı.

-- ---------------------------------------------------------------------------
-- water_logs — günlük su tüketimi
-- ---------------------------------------------------------------------------
CREATE TABLE water_logs (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- auth_db'deki users.id ile aynı değer. FOREIGN KEY YOK: başka veritabanı
    -- (ADR 0005). Bütünlük AccountDeleted olayıyla korunuyor.
    user_id    UUID        NOT NULL,

    -- ★ KULLANICININ YEREL GÜNÜ ★
    -- İstemci kendi takvimindeki günü gönderiyor. Burada `TIMESTAMPTZ` yerine
    -- `DATE` olmasının sebebi bu: su tüketimi bir AN değil, bir GÜNÜN toplamı.
    -- Zaman damgası saklasaydık gün sınırı yine saat dilimi sorunu doğururdu
    -- (bkz. workout-service `localday.py`).
    log_date   DATE        NOT NULL,

    -- ★ TOPLAM, TEK TEK KAYIT DEĞİL ★
    -- Kullanıcı gün içinde birden çok kez su ekliyor ama her ekleme ayrı satır
    -- OLMUYOR: gün başına tek satır tutulup üstüne ekleniyor. Sebep, sorulan
    -- sorunun "bugün ne kadar içtim" olması — "saat 14:32'de 200 ml içtim"
    -- bilgisinin hiçbir tüketicisi yok ve satır sayısını günde 8-10 katına
    -- çıkarırdı.
    amount_ml  INTEGER     NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- 0 GEÇERLİ: kullanıcı yanlışlıkla eklediğini sıfıra çekebilmeli.
    -- Üst sınır 20 litre — fiziksel olarak anlamsızın ötesi (su zehirlenmesi
    -- eşiği ~6 L/gün), yani bu bir veri girişi hatası demek.
    CONSTRAINT water_logs_amount_range CHECK (amount_ml >= 0 AND amount_ml <= 20000),

    -- Gün başına tek satır — yukarıdaki "toplam" kararının şema karşılığı.
    CONSTRAINT water_logs_unique_day UNIQUE (user_id, log_date)
);

-- Hem tek gün (`= date`) hem aralık (`BETWEEN`) sorgusunu karşılıyor.
CREATE INDEX water_logs_user_date_idx ON water_logs (user_id, log_date);

-- ---------------------------------------------------------------------------
-- processed_events — hesap silme olayını tekrara dayanıklı tüketmek için
-- ---------------------------------------------------------------------------
-- Diğer servislerdeki tabloyla birebir aynı; ADR 0006 idempotent consumer.
CREATE TABLE processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX processed_events_processed_at_idx ON processed_events (processed_at);
