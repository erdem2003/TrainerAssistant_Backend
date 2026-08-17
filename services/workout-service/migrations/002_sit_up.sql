-- ---------------------------------------------------------------------------
-- 002 — mekik (sit_up) egzersiz kataloğuna eklenir
-- ---------------------------------------------------------------------------
--
-- NEDEN AYRI MIGRATION, NEDEN 001'E EKLENMEDİ:
-- 001 çalışmış ve `schema_migrations` tablosuna yazılmış durumda. Uygulanmış bir
-- migration'ı düzenlemek, yeni kurulumla mevcut kurulumun şemasını sessizce
-- ayrıştırır — mevcut veritabanı 001'i tekrar çalıştırmaz, dolayısıyla satırı
-- hiç görmez ve `sit_up` kaydı FK ihlaliyle reddedilir.
--
-- `workouts.exercise_id` bu tabloya REFERENCES ile bağlı; seed olmadan mobil
-- taraftan gelen mekik kaydı 500 alır.
--
-- ON CONFLICT: migration'ın tekrar çalıştırılması (ör. elle) hata vermesin.

INSERT INTO exercises (id, display_name, required_view)
VALUES ('sit_up', 'Mekik', 'SIDE')
ON CONFLICT (id) DO NOTHING;
