-- Yoruma yorum (Twitter tarzı yanıt), ADR 0014'ün gönderi/yorum modelinin
-- doğal uzantısı — ayrı bir ADR gerektirmiyor (yeni bir servis sınırı, veri
-- sınırı ya da mimari karar değil, mevcut `post_comments` tablosunun tek
-- seviye kendine referansı).
--
-- ★ TEK SEVİYE, SONSUZ DERİNLİK DEĞİL ★ Yanıtın yanıtı yok — Twitter'ın
-- kendisi de UI'da derin zincirleri düzleştirir. `parent_comment_id` NULL ise
-- üst seviye yorum, dolu ise doğrudan o yoruma yanıt. Uygulama/mobil taraf
-- bir yanıta "yanıtla" göstermeyerek bunu zorluyor (CLAUDE.md §2 —
-- egzersiz motorunun tersine burada karmaşıklığı kısıtlayan taraf UI).
ALTER TABLE post_comments ADD COLUMN parent_comment_id UUID
    REFERENCES post_comments (id) ON DELETE CASCADE;

CREATE INDEX post_comments_parent_idx ON post_comments (parent_comment_id, created_at);
