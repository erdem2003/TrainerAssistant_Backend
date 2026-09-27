-- Faz S1 iskeleti: sema henuz yok, yalnizca `schema_migrations` bootstrap'i
-- `db.py` tarafindan zaten uygulaniyor. Bu dosya, migration mekanizmasinin
-- gercekten calistigini kanitlamak icin bos degil, bir islenmez tablo icin var —
-- `processed_events`, hesap silme fanout'u (Faz S10) icin zaten gerekecek ve
-- simdiden eklemek sonraki migration'i basitlestiriyor.
CREATE TABLE processed_events (
    event_id    UUID        PRIMARY KEY,
    event_type  TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
