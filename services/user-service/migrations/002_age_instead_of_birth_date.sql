-- Doğum tarihi yerine yaş.
--
-- NEDEN AYRI MIGRATION, 001'İ DÜZENLEMEK YERİNE:
-- 001 zaten uygulandı. Uygulanmış bir migration'ı düzenlemek, o dosyayı çalıştırmış
-- ortamlarla çalıştıracak ortamların ŞEMALARININ AYRIŞMASI demek — `schema_migrations`
-- 001'i uygulanmış saydığı için yeni hâli hiçbir zaman koşmaz. Kural: uygulanmış
-- migration değişmez, üstüne yenisi yazılır.
--
-- ★ BİLİNEN BEDEL ★
-- Yaş bir ÖLÇÜM DEĞİL, ZAMAN İÇİNDE BAYATLAYAN bir sayı. 25 yazan kullanıcı bir yıl
-- sonra hâlâ 25 görünecek; profilini güncellemedikçe veri sessizce yanlışlaşır.
-- Doğum tarihi bu sorunu tanımı gereği yaşamaz. Tercih kullanıcının bilinçli kararı:
-- onboarding'de yaş sormak tek bir sayı girişi, doğum tarihi ise takvim seçici
-- gerektiriyordu.
--
-- İleride doğum tarihine dönülmek istenirse: mevcut `age` değerlerinden tarih GERİ
-- ÜRETİLEMEZ (yalnızca yıl tahmin edilebilir). O geçiş, kullanıcılara tarihi tekrar
-- sormayı gerektirir.

ALTER TABLE profiles DROP COLUMN birth_date;

-- Sınırlar 001'deki birth_date doğrulamasıyla aynı aralık:
--   13 alt sınır — çocuk verisi işlemek ayrı bir yükümlülük sınıfı (KVKK/COPPA)
--                  ve bu proje onu karşılamıyor.
--   120 üst sınır — doğrulanmış en yaşlı insan 122 yaşındaydı; ötesi giriş hatası.
ALTER TABLE profiles ADD COLUMN age INTEGER NULL;

ALTER TABLE profiles ADD CONSTRAINT profiles_age_range
    CHECK (age IS NULL OR (age >= 13 AND age <= 120));
