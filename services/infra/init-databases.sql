-- ADR 0005: database-per-service. Hicbir servis baskasinin veritabanina dokunmaz.
--
-- Yerel gelistirmede tek Postgres ornegi calisiyor ama veritabanlari AYRI.
-- Uretimde ayri orneklere bolmek yalnizca baglanti dizesi degistirmek demek —
-- sinir kod tarafinda zaten var.
CREATE DATABASE auth_db;
CREATE DATABASE user_db;
CREATE DATABASE workout_db;
CREATE DATABASE analytics_db;
-- ADR 0010: gunluk saglik kaydi (su, ileride uyku ve kilo gecmisi).
CREATE DATABASE health_db;
