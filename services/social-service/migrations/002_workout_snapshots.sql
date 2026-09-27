-- Antrenman izdusumu (ADR 0014, Faz S3).
--
-- `workout.session` event'inin bu servisteki READ MODEL'i — `analytics_db.
-- workout_facts`'in birebir ayni sekli, ama BAGIMSIZ tablo: iki servis ayni
-- Kafka olayini kendi hizinda, kendi tuketici grubuyla okur, birbirinin
-- semasindan haberdar degil (ADR 0005, database-per-service).
--
-- Bu tablo iki tuketicinin temeli olacak: Faz S4 (gonderi "PENDING_SNAPSHOT"
-- durumundan "VISIBLE"a bu tablo doldugunda gecer) ve Faz S5 (haftalik skor
-- tablosu SORGU ANINDA bu tablodan hesaplanir, ADR 0012 — sayac sutunu yok).
CREATE TABLE workout_snapshots (
    workout_id            UUID        PRIMARY KEY,
    user_id                UUID        NOT NULL,
    exercise_id             TEXT        NOT NULL,
    started_at              TIMESTAMPTZ NOT NULL,
    ended_at                TIMESTAMPTZ,
    total_sets              INTEGER     NOT NULL DEFAULT 0,
    total_reps              INTEGER     NOT NULL DEFAULT 0,
    reps_with_errors        INTEGER     NOT NULL DEFAULT 0,
    best_set_reps           INTEGER     NOT NULL DEFAULT 0,
    total_active_seconds    DOUBLE PRECISION NOT NULL DEFAULT 0,
    form_errors              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    projected_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Faz S4: "bu workout_id icin bekleyen gonderi var mi" kontrolu author_id
-- (= user_id) ile birlikte yapiliyor. Faz S5: haftalik skor tablosu
-- (user_id, started_at) araligiyla sorgulanacak — arkadas listesindeki her
-- kullanici icin.
CREATE INDEX workout_snapshots_user_started_idx
    ON workout_snapshots (user_id, started_at);
