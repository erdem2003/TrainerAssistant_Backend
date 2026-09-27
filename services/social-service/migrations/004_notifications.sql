-- Bildirimler (ADR 0014, Faz S8).
--
-- ★ DOĞAL ANAHTAR + UPSERT ★ Bir kullanıcı bir gönderiyi beğenip kaldırıp
-- tekrar beğenirse İKİ satır değil, TEK satır kalır (`created_at` güncellenir,
-- `read_at` sıfırlanır) — `UNIQUE (recipient_id, type, actor_id, subject_id)`.
-- Sebep: sayaç değil bildirim listesi tutuyoruz; aynı eylemin tekrarı yeni bir
-- bildirim değil, VAROLANI güncel bir olay olarak taşımalı.
--
-- `subject_id` egzersiz/gönderi/arkadaşlık gibi bağlama göre değişen bir
-- referans (post_id, ya da arkadaşlık bildirimlerinde actor_id'nin kendisi —
-- bkz. altta) — foreign key DEĞİL çünkü hedef tablo `type`'a göre değişiyor
-- (posts, friendships, ...).
--
-- ★ subject_id ASLA NULL DEĞİL ★ Postgres UNIQUE kısıtında NULL'lar
-- birbirinden FARKLI sayılır — `subject_id` NULL olabilseydi aynı kişiden
-- gelen iki arkadaşlık isteği bildirimi dedup OLMAZDI. Arkadaşlık
-- bildirimlerinde `subject_id = actor_id` yazılır (app/repo/notifications.py).
CREATE TABLE notifications (
    id           UUID        PRIMARY KEY,
    recipient_id UUID        NOT NULL,
    type         TEXT        NOT NULL
                 CHECK (type IN ('FRIEND_REQUEST', 'FRIEND_ACCEPTED', 'POST_LIKED', 'POST_COMMENTED')),
    actor_id     UUID        NOT NULL,
    subject_id   UUID        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at      TIMESTAMPTZ,
    UNIQUE (recipient_id, type, actor_id, subject_id)
);

-- Liste sorgusu: alıcı + tarih inişi, sayfalama icin.
CREATE INDEX notifications_recipient_created_idx ON notifications (recipient_id, created_at DESC);

-- "Okunmamış sayısı" rozet sorgusu icin kısmi indeks.
CREATE INDEX notifications_recipient_unread_idx ON notifications (recipient_id) WHERE read_at IS NULL;
