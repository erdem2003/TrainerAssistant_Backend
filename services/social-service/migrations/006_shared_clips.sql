-- İskelet klibi paylaşımı (ADR 0015, Faz S11).
--
-- ★ YALNIZCA LANDMARK DİZİSİ — HİÇ GÖRÜNTÜ YOK ★ `landmark_sequence`,
-- mobil `RepClip.frames`'in (`List<PoseFrame>`) JSON karşılığı: her kare
-- `{"t": nanos, "landmarks": {"LEFT_ELBOW": [x, y, likelihood], ...}}`.
-- Kamera görüntüsü, bitmap, video — hiçbiri bu tabloya hiç girmez (ADR 0002,
-- ADR 0015'in "kapsam netleştirme" bölümü).
--
-- ★ TEK KLİP, GÖNDERİYLE BİREBİR ★ Bir gönderi en fazla bir klip taşır —
-- ADR 0015'in "elle seçim" kararı: kullanıcı antrenman bitince tek bir
-- hatalı tekrarı işaretliyor, tüm seti değil. `post_id` hem PK hem FK.
-- `image_width`/`image_height`: mobil `PoseOverlay`'in `ViewTransform.
-- fitCenter`'ı koordinatları bu boyuta göre ölçekliyor — kaydedilmezse
-- oynatıcı skeleton'ı yanlış oranla çizer (kamera görüntüsünün KENDİSİ
-- değil, yalnızca boyutu — ADR 0002'yi ihlal etmiyor).
CREATE TABLE shared_clips (
    post_id           UUID        PRIMARY KEY REFERENCES posts (id) ON DELETE CASCADE,
    landmark_sequence JSONB       NOT NULL,
    frame_count       INTEGER     NOT NULL CHECK (frame_count > 0 AND frame_count <= 450),
    form_errors       TEXT[]      NOT NULL DEFAULT '{}',
    image_width       INTEGER     NOT NULL CHECK (image_width > 0),
    image_height       INTEGER     NOT NULL CHECK (image_height > 0),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Gönderi silinince (hesap silme dahil, posts zaten CASCADE ile silinir)
-- klip de kendiliğinden gider — ADR 0015'in "ayrı bir yaşam döngüsü yok"
-- kararı, ek bir silme kodu gerektirmiyor.
