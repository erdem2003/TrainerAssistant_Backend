-- Motivasyon gönderisi: antrenmana bağlı olmayan serbest metin + opsiyonel
-- fotoğraf (ADR 0016).
--
-- `workout_id` artık NULL olabilir — yalnızca WORKOUT tipi gönderiler için
-- zorunlu kalıyor (aşağıdaki CHECK). Fotoğraf MinIO'da `post_id` anahtarıyla
-- duruyor (gönderi başına en fazla 1 fotoğraf, ayrı bir obje-anahtarı
-- kolonu gerekmiyor) — `photo_content_type` NULL olmaması "fotoğrafı var"
-- demek, `app/routers/posts.py`'nin `has_photo` alanı bunu okuyor.
ALTER TABLE posts ALTER COLUMN workout_id DROP NOT NULL;

ALTER TABLE posts ADD COLUMN post_type TEXT NOT NULL DEFAULT 'WORKOUT'
    CHECK (post_type IN ('WORKOUT', 'MOTIVATION'));

ALTER TABLE posts ADD COLUMN photo_content_type TEXT;

-- WORKOUT gönderisi workout_id'siz olamaz; MOTIVATION gönderisi workout_id
-- TAŞIYAMAZ (feed sorgusundaki LEFT JOIN workout_snapshots'ın anlamsız bir
-- satırla eşleşmesini önlüyor).
ALTER TABLE posts ADD CONSTRAINT posts_type_shape_chk CHECK (
    (post_type = 'WORKOUT' AND workout_id IS NOT NULL)
    OR
    (post_type = 'MOTIVATION' AND workout_id IS NULL)
);
