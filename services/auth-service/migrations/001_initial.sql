-- auth_db · 001 — ilk şema
--
-- Ham SQL, ORM yok. Sorgular okunabilir ve gözden geçirilebilir olsun diye
-- bilinçli tercih; ADR 0005'in "her servis kendi migration'ını taşır" kuralı
-- numaralı dosyalar + schema_migrations tablosuyla sağlanıyor.

-- gen_random_uuid() için. Postgres 13+ ile birlikte geliyor.
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
-- email UYGULAMADA normalize edilir (lower + trim), burada düz TEXT + UNIQUE.
-- citext eklentisi yerine bu tercih edildi: eklenti bağımlılığı yok ve
-- normalizasyonun nerede yapıldığı kodda açıkça görünüyor.
CREATE TABLE users (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email             TEXT        NOT NULL UNIQUE,
    password_hash     TEXT        NOT NULL,
    email_verified_at TIMESTAMPTZ,
    status            TEXT        NOT NULL DEFAULT 'PENDING_VERIFICATION',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT users_status_check
        CHECK (status IN ('PENDING_VERIFICATION', 'ACTIVE', 'DISABLED')),

    -- Doğrulanmış hesabın email_verified_at'i dolu olmak ZORUNDA. İki alanın
    -- birbirine düşmesi (status=ACTIVE ama tarih boş) sessiz bir tutarsızlık
    -- olurdu; veritabanı bunu kabul etmesin.
    CONSTRAINT users_verified_consistency
        CHECK (status <> 'ACTIVE' OR email_verified_at IS NOT NULL)
);


-- ---------------------------------------------------------------------------
-- verification_codes
-- ---------------------------------------------------------------------------
-- purpose ayrımı bilinçli: e-posta doğrulama ve parola sıfırlama aynı mekanizmayı
-- kullanıyor (6 hane, süreli, deneme sayaçlı). Parola sıfırlama henüz yazılmadı
-- ama tablo onu kaldıracak şekilde tasarlandı.
--
-- code_hash: bcrypt. Düz metin saklamak, veritabanı sızdığında saldırganın hesap
-- doğrulamasına izin verirdi — kod da bir credential.
CREATE TABLE verification_codes (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose        TEXT        NOT NULL,
    code_hash      TEXT        NOT NULL,
    expires_at     TIMESTAMPTZ NOT NULL,
    attempts       SMALLINT    NOT NULL DEFAULT 0,
    consumed_at    TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT verification_codes_purpose_check
        CHECK (purpose IN ('EMAIL_VERIFY', 'PASSWORD_RESET'))
);

-- Aynı anda tek AKTİF kod. Yeni kod üretmek eskisini geçersiz kılmak zorunda;
-- iki geçerli kodun aynı anda dolaşması deneme sayacını anlamsız kılardı
-- (saldırgan her kod için ayrı 3 hak kazanır).
CREATE UNIQUE INDEX verification_codes_one_active
    ON verification_codes (user_id, purpose)
    WHERE consumed_at IS NULL AND invalidated_at IS NULL;


-- ---------------------------------------------------------------------------
-- refresh_tokens
-- ---------------------------------------------------------------------------
-- family_id ROTASYON AİLESİDİR ve bu tablonun en önemli sütunudur.
--
-- Rotasyonun tek amacı çalınmış token'ı yakalamaktır. "Eskiyi iptal et" yetmez;
-- asıl soru, ZATEN KULLANILMIŞ bir token tekrar sunulduğunda ne olacağıdır.
-- Bu ya replay ya hırsızlıktır — o zaman ailenin TAMAMI iptal edilir ve kullanıcı
-- yeniden girişe zorlanır. Bu kontrol olmadan rotasyon hiçbir şey kazandırmaz.
--
-- token_hash: SHA-256. Parolanın aksine bcrypt gerekmiyor — token 32 bayt
-- rastgele, yani sözlük/brute-force saldırısına açık değil. Yavaş hash yalnızca
-- düşük entropili sırlar için gerekli.
CREATE TABLE refresh_tokens (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id      UUID        NOT NULL,
    parent_id      UUID        REFERENCES refresh_tokens(id) ON DELETE SET NULL,
    token_hash     TEXT        NOT NULL UNIQUE,
    issued_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    used_at        TIMESTAMPTZ,
    revoked_at     TIMESTAMPTZ,
    revoked_reason TEXT,
    device_label   TEXT,

    CONSTRAINT refresh_tokens_reason_check
        CHECK (revoked_reason IS NULL OR revoked_reason IN
               ('ROTATED', 'LOGOUT', 'REUSE_DETECTED', 'PASSWORD_CHANGED'))
);

CREATE INDEX refresh_tokens_user_idx    ON refresh_tokens (user_id);
CREATE INDEX refresh_tokens_family_idx  ON refresh_tokens (family_id);
-- Süresi geçmiş token'ları temizleyen periyodik iş bu index'i kullanacak.
CREATE INDEX refresh_tokens_expires_idx ON refresh_tokens (expires_at);


-- ---------------------------------------------------------------------------
-- outbox
-- ---------------------------------------------------------------------------
-- E-posta gönderimi DOĞRUDAN yapılmaz. Kayıt işlemiyle AYNI TRANSACTION'da
-- buraya yazılır, ayrı bir worker gönderir.
--
-- Sebep: "kullanıcı oluşturuldu ama mail gitmedi" ya da tersi, iki farklı sisteme
-- yazan her serviste kaçınılmazdır. Outbox bunu tek transaction'a indirger.
-- Phase 11'de relay Kafka'ya publish etmeye başlayacak; BU TABLOYA YAZAN KOD
-- HİÇ DEĞİŞMEYECEK.
CREATE TABLE outbox (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type    TEXT        NOT NULL,
    topic         TEXT        NOT NULL,
    partition_key TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ,
    attempts      SMALLINT    NOT NULL DEFAULT 0,
    last_error    TEXT
);

-- Kısmi index: worker yalnızca yayınlanmamış satırları tarıyor. Tablo büyüdükçe
-- (yayınlanmışlar birikir) tarama maliyeti sabit kalır.
CREATE INDEX outbox_unpublished_idx
    ON outbox (created_at)
    WHERE published_at IS NULL;
