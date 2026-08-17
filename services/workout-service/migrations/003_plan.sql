-- Günlük antrenman programı.
--
-- Kullanıcı "bugün toplam 5 şınav, 8 mekik yapacağım" diyebilsin; anasayfa
-- bunun ne kadarının tamamlandığını göstersin; Schedule ekranı gün gün
-- hedefi ve yapılanı yan yana koysun.
--
-- ★ NEDEN BU TABLO workout-service'TE ★
-- Plan satırı `exercises` tablosuna referans veriyor ve tamamlanma `workouts`
-- kayıtlarından hesaplanıyor. İkisi de bu veritabanında. user-service'e
-- koysaydık servisler arası foreign key gerekirdi — ADR 0005 (database per
-- service) bunu yasaklıyor. Ayrıca tamamlanma sorgusu servisler arası bir
-- JOIN'e dönüşürdü.

-- ---------------------------------------------------------------------------
-- plan_items — bir günün program kalemleri
-- ---------------------------------------------------------------------------
-- ★ TAMAMLANMA BU TABLODA TUTULMUYOR ★
-- "Yapıldı" diye bir kolon YOK ve olmayacak. Tamamlanma, o güne ait `reps`
-- satırları sayılarak TÜRETİLİYOR. Saklansaydı iki doğruluk kaynağı olurdu:
-- kullanıcı antrenmanı yapar ama kutu işaretlenmezse hangisi doğru? Ayrıca
-- workout veri sözleşmesi DONMUŞ (CLAUDE.md §4, ADIM 19) — antrenman gövdesine
-- `plan_item_id` eklemek o sözleşmeyi kırardı.
--
-- Türetmenin üç yan faydası daha var:
--   1. Plansız yapılan antrenman da ilerleme sayılır
--   2. İstemcinin "bu tekrar hangi kalemi dolduruyor" kararı vermesi gerekmez
--   3. Plan sonradan değişince yetim kayıt kalmaz
CREATE TABLE plan_items (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- auth_db'deki users.id ile aynı değer. FOREIGN KEY YOK: başka veritabanı
    -- (ADR 0005). Bütünlük AccountDeleted olayıyla korunuyor.
    user_id        UUID        NOT NULL,

    -- ★ KULLANICININ YEREL GÜNÜ ★, UTC değil.
    -- Sunucu istemcinin saat dilimini bilmiyor; İstanbul'da 01:00'de yapılan
    -- antrenman UTC'de bir önceki güne düşer. Bu yüzden gün, istemcinin
    -- takvimine göre DATE olarak saklanıyor ve tamamlanma sorgusu gün sınırını
    -- istemciden gelen `tz_offset` ile hesaplıyor.
    scheduled_date DATE        NOT NULL,

    exercise_id    TEXT        NOT NULL REFERENCES exercises(id),

    -- O GÜNÜN TOPLAM hedefi — set başına değil.
    -- Kullanıcının ifadesi "toplam 5 şınav": setlere nasıl böldüğü kendi
    -- bileceği iş, motor zaten seti otomatik ayırıyor (SetTracker).
    target_reps    SMALLINT    NOT NULL,

    -- Opsiyonel planlanan saat ("08:30"). Referans tasarımda kartların üstünde
    -- duruyor. NULL bırakılabilir: saat vermek zorunda kalmak, iki dokunuşluk
    -- bir işi form doldurmaya çevirirdi.
    scheduled_time TIME        NULL,

    -- Listedeki sırası, 1'den başlar.
    position       SMALLINT    NOT NULL,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT plan_items_target_range CHECK (target_reps BETWEEN 1 AND 1000),
    CONSTRAINT plan_items_position_positive CHECK (position >= 1),

    -- ★ GÜN + EGZERSİZ BAŞINA TEK SATIR ★
    -- Referans tasarım aynı güne iki "Pushups session" kartı koymuş ama bu,
    -- ilerleme atfını belirsizleştirir: kullanıcı 5 şınav çekti, iki karttan
    -- hangisi doldu? Tek satır olunca soru ortadan kalkıyor — o günün toplam
    -- şınav sayısı tek bir hedefle karşılaştırılıyor.
    CONSTRAINT plan_items_unique_exercise UNIQUE (user_id, scheduled_date, exercise_id)
);

-- Hem tek gün (`= date`) hem aralık (`BETWEEN`) sorgusunu karşılıyor.
CREATE INDEX plan_items_user_date_idx ON plan_items (user_id, scheduled_date);
