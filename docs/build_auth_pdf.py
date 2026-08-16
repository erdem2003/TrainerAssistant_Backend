# -*- coding: utf-8 -*-
"""auth-service PDF'ini üretir. Çalıştırma: python docs/build_auth_pdf.py"""

from __future__ import annotations

from reportlab.lib import colors as _c
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from generate_service_docs import (
    FONT_B,
    INK,
    LINE,
    FlowDiagram,
    Relations,
    S_CELL,
    S_H1,
    S_H2,
    S_SMALL,
    body,
    build,
    note,
    schema_table,
)

story = []

# =============================================================================
# 1. Servis ne yapar
# =============================================================================
story += [
    Paragraph("1. Servis ne yapar", S_H1),
    body(
        "<b>auth-service</b>, sistemin kimlik sağlayıcısıdır. Tek sorumluluğu "
        "<b>kullanıcının kim olduğuna karar vermek</b>: hesap açmak, e-posta adresinin "
        "gerçekten o kişiye ait olduğunu doğrulamak, token üretmek ve iptal etmek."
    ),
    body(
        "Kullanıcının boyu, kilosu, antrenman geçmişi burada <b>tutulmaz</b>. ADR 0005 "
        "servis sınırlarını veriyle çizdi: bir bileşen, kendi verisinin tek sahibiyse "
        "servistir. Parola özetine (hash) başka hiçbir servis dokunmaz."
    ),
    note(
        "<b>Profilden neden ayrı:</b> auth-service fiilen kendi kimlik sağlayıcımızdır "
        "(Identity Provider). Kimlik yönetimini profil verisinden ayırmak sektörün fiili "
        "standardıdır — Keycloak, Auth0 ve Firebase Auth aynı şekilde çalışır. Yarın "
        "auth-service yönetilen bir sağlayıcıyla değiştirilirse user-service hiç "
        "dokunulmadan ayakta kalır. Ayrıca profil neredeyse her ekranda okunur; her "
        "okumada parola özetlerinin durduğu veritabanına dokunmak istemeyiz."
    ),
    Paragraph(
        "Veritabanı: <font face='Courier'>auth_db</font> &nbsp;·&nbsp; "
        "Port: 8001 (konteyner içinde 8000)", S_SMALL,
    ),
]

# =============================================================================
# 2. Tablolar
# =============================================================================
story += [Paragraph("2. Veritabanı tabloları", S_H1)]

story.append(schema_table(
    "users", "Hesabın kendisi. Sistemdeki kimliğin tek kaynağı.",
    [
        ("id", "uuid", "PK — diğer tüm tablolar buna bağlanır"),
        ("email", "text", "UNIQUE. Uygulamada lower(trim(email)) ile normalleştirilir"),
        ("password_hash", "text", "bcrypt, cost 12. Parolanın kendisi hiçbir yerde saklanmaz"),
        ("email_verified_at", "timestamptz", "NULL ise adres henüz doğrulanmadı"),
        ("status", "text", "PENDING_VERIFICATION | ACTIVE | DISABLED"),
        ("created_at", "timestamptz", "Kayıt anı"),
        ("updated_at", "timestamptz", "Son değişiklik"),
    ],
))

story.append(schema_table(
    "verification_codes",
    "6 haneli kodlar. E-posta doğrulama ve parola sıfırlama aynı tabloyu kullanır.",
    [
        ("id", "uuid", "PK"),
        ("user_id", "uuid", "FK → users(id) ON DELETE CASCADE"),
        ("purpose", "text", "EMAIL_VERIFY | PASSWORD_RESET"),
        ("code_hash", "text", "bcrypt. Kod düz metin saklanmaz — o da bir kimlik bilgisidir"),
        ("expires_at", "timestamptz", "10 dakika geçerli"),
        ("attempts", "smallint", "Yanlış deneme sayacı; 3'te kod geçersiz kılınır"),
        ("consumed_at", "timestamptz", "Doğru girildi ve kullanıldı"),
        ("invalidated_at", "timestamptz", "3 yanlış deneme ya da yeni kod üretildi"),
        ("created_at", "timestamptz", ""),
    ],
))
story.append(note(
    "<b>Kısmi UNIQUE indeks:</b> <font face='Courier'>(user_id, purpose)</font> üzerinde, "
    "yalnızca <font face='Courier'>consumed_at IS NULL AND invalidated_at IS NULL</font> "
    "koşuluyla tanımlı. Böylece bir kullanıcının aynı amaç için aynı anda <b>tek aktif "
    "kodu</b> olabiliyor; tüketilmiş kodlar satırda kalıyor ama benzersizliği bozmuyor."
))

story.append(PageBreak())

story.append(schema_table(
    "refresh_tokens",
    "Oturumlar. Rotasyon ve çalıntı token tespitinin tamamı bu tabloda.",
    [
        ("id", "uuid", "PK"),
        ("user_id", "uuid", "FK → users(id) ON DELETE CASCADE"),
        ("family_id", "uuid", "Rotasyon ailesi — aynı oturumdan türeyen bütün token'lar"),
        ("parent_id", "uuid", "FK → refresh_tokens(id). Bu token hangisinden türedi"),
        ("token_hash", "text", "UNIQUE, SHA-256. Token yüksek entropili; yavaş hash gereksiz"),
        ("issued_at", "timestamptz", ""),
        ("expires_at", "timestamptz", "30 gün"),
        ("used_at", "timestamptz", "Döndürüldü — bir daha kullanılamaz"),
        ("revoked_at", "timestamptz", "İptal edildi"),
        ("revoked_reason", "text", "ROTATED | LOGOUT | REUSE_DETECTED | PASSWORD_CHANGED"),
        ("device_label", "text", "Cihaz adı, örneğin telefon modeli"),
    ],
))

story.append(schema_table(
    "outbox",
    "Yayınlanacak olaylar. İş verisiyle aynı transaction'da yazılır (ADR 0006).",
    [
        ("id", "uuid", "PK. Aynı zamanda event_id — tüketicinin tekrar koruma anahtarı"),
        ("event_type", "text", "EmailVerificationRequested, AccountDeleted, …"),
        ("topic", "text", "Phase 11'de Kafka konusu olacak"),
        ("partition_key", "text", "user_id — bir kullanıcının olayları sıralı işlenir"),
        ("payload", "jsonb", "Olay gövdesi. Kendine yeter: tüketici geri soru sormaz"),
        ("created_at", "timestamptz", ""),
        ("published_at", "timestamptz", "NULL ise henüz işlenmedi"),
        ("attempts", "smallint", "5'e ulaşınca worker vazgeçer; sonsuz döngü oluşmaz"),
        ("last_error", "text", "Son hata metni — teşhis için"),
    ],
))
story.append(note(
    "<b>outbox'ın users'a yabancı anahtarı YOK</b> ve bu bilinçli. Hesap silindiğinde "
    "<font face='Courier'>AccountDeleted</font> olayının yine de gönderilmesi gerekiyor; "
    "yabancı anahtar olsaydı satır kullanıcıyla birlikte silinir ve haber hiçbir yere "
    "ulaşmazdı."
))

story.append(schema_table(
    "schema_migrations",
    "Uygulanmış migration'lar. Alembic yok; numaralı düz .sql dosyaları kullanılıyor.",
    [("version", "text", "PK — dosya adı, örneğin 001_initial"),
     ("applied_at", "timestamptz", "")],
))

# =============================================================================
# 3. İlişkiler
# =============================================================================
story += [
    PageBreak(),
    Paragraph("3. Tablolar arası ilişki", S_H1),
    body(
        "İlişkilerin merkezinde <font face='Courier'>users</font> tablosu var. İki tablo "
        "ona <b>CASCADE</b> ile bağlı: kullanıcı silindiğinde doğrulama kodları ve "
        "oturum token'ları veritabanı tarafından otomatik silinir. Temizliği uygulama "
        "kodunun yapması gerekmez — dolayısıyla unutulamaz."
    ),
    Spacer(1, 4 * mm),
    Relations(
        root="users",
        children=[("verification_codes", "CASCADE"), ("refresh_tokens", "CASCADE")],
        detached=[("outbox", "— bilinçli olarak yabancı anahtar yok"),
                  ("schema_migrations", "— altyapı tablosu, ilişkisiz")],
    ),
    Spacer(1, 4 * mm),
    body(
        "<font face='Courier'>refresh_tokens</font> ayrıca <b>kendi kendine</b> bağlı: "
        "<font face='Courier'>parent_id → refresh_tokens(id)</font>. Her yenileme yeni bir "
        "satır üretir ve bir öncekini işaret eder; böylece bir oturumun bütün geçmişi "
        "zincir hâlinde izlenebilir."
    ),
]

# =============================================================================
# 4. Uçlar
# =============================================================================
story += [
    Paragraph("4. API uçları", S_H1),
    body("Tümü api-gateway (<font face='Courier'>:8080</font>) üzerinden geçer."),
]

_rows = [["Uç", "Yanıt", "Ne yapar"]]
for _ep, _st, _desc in [
    ("POST /v1/auth/registrations", "202", "Kayıt. Her durumda aynı yanıt"),
    ("POST /v1/auth/registrations/verify", "200", "Kodu doğrula → token çifti"),
    ("POST /v1/auth/registrations/resend", "202", "Yeni kod iste (hız sınırlı)"),
    ("POST /v1/auth/sessions", "200", "Giriş → token çifti"),
    ("POST /v1/auth/sessions/refresh", "200", "Rotasyon + tekrar kullanım tespiti"),
    ("DELETE /v1/auth/sessions", "204", "Çıkış — token ailesini iptal eder"),
    ("POST /v1/auth/password-resets", "202", "Sıfırlama kodu iste"),
    ("POST /v1/auth/password-resets/confirm", "200", "Kod + yeni parola → token çifti"),
    ("PUT /v1/auth/password", "200", "Parola değiştir (mevcut parola gerekir)"),
    ("DELETE /v1/auth/account", "204", "Hesabı sil (parola gerekir)"),
    ("GET /v1/auth/me", "200", "Kimlik bilgisi"),
    ("GET /v1/auth/introspect", "200", "Gateway'in token doğrulaması (dahili)"),
]:
    _rows.append([
        Paragraph(f'<font face="Courier" size="7.5">{_ep}</font>', S_CELL),
        Paragraph(_st, S_CELL),
        Paragraph(_desc, S_CELL),
    ])

_t = Table(_rows, colWidths=[68 * mm, 14 * mm, 86 * mm], repeatRows=1)
_t.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), INK),
    ("TEXTCOLOR", (0, 0), (-1, 0), _c.white),
    ("FONTNAME", (0, 0), (-1, 0), FONT_B),
    ("FONTSIZE", (0, 0), (-1, 0), 8),
    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
]))
story += [_t]

# =============================================================================
# 5. Akışlar
# =============================================================================
story += [
    PageBreak(),
    Paragraph("5. Sistem nasıl çalışır", S_H1),

    Paragraph("5.1 Kayıt ve e-posta doğrulama", S_H2),
    body(
        "Kayıt ucu <b>her durumda 202</b> döner — adres ister yeni olsun, ister zaten "
        "kayıtlı. Farklı yanıt vermek, saldırganın hangi adreslerin sistemde olduğunu "
        "öğrenmesini sağlardı (hesap sayımı / enumeration)."
    ),
    FlowDiagram([
        ("Mobil", "POST /v1/auth/registrations { email, password }"),
        ("auth-service", "Kullanıcı (PENDING) + kod + outbox kaydı — HEPSİ TEK TRANSACTION"),
        ("auth-service", "202 döner. E-posta henüz gönderilmedi"),
        ("email-worker", "outbox'ı saniyede bir tarar, SMTP ile gönderir, published_at yazar"),
        ("Mobil", "POST /registrations/verify { email, code } → token çifti, hesap ACTIVE"),
    ]),
    note(
        "<b>Outbox neden var:</b> e-posta gönderimi kayıt transaction'ının içinde olsaydı, "
        "SMTP yavaşladığında kayıt da yavaşlar; SMTP hata verdiğinde kayıt geri alınırdı. "
        "Outbox ikisini ayırır ama <b>hiçbirini kaybetmez</b>: olay iş verisiyle aynı "
        "transaction'da yazıldığı için biri olup diğeri olmaz."
    ),
    Spacer(1, 3 * mm),
    body(
        "<b>Üç yanlış kod</b> girildiğinde kod geçersiz kılınır ama <b>otomatik yeni kod "
        "gönderilmez</b>. Gönderilseydi saldırgan kurbanın gelen kutusunu bombalayabilirdi: "
        "yanlış kod gir → yeni e-posta → tekrarla. Kullanıcının 'Tekrar gönder'e basması "
        "gerekir ve o uç ayrıca hız sınırlıdır."
    ),
]

story += [
    PageBreak(),
    Paragraph("5.2 Token'lar ve yenileme", S_H2),
    body(
        "<b>Erişim token'ı (access):</b> RS256 imzalı JWT, 15 dakika, veritabanında "
        "saklanmaz. Gateway onu yalnızca <b>açık anahtarla</b> doğrular; özel anahtar "
        "auth-service'te kalır."
    ),
    body(
        "<b>Yenileme token'ı (refresh):</b> 32 baytlık opak rastgele değer, 30 gün, "
        "SHA-256 özeti saklanır. JWT değildir çünkü <b>iptal edilebilir</b> olmak "
        "zorundadır; durumsuz bir JWT'yi iptal etmek için kara liste gerekir, o da "
        "veritabanı sorgusu demektir — yani durumsuzluk hiçbir kazanç sağlamadan "
        "kaybedilirdi."
    ),
    Spacer(1, 2 * mm),
    Paragraph("Rotasyon ve çalıntı token tespiti", S_H2),
    FlowDiagram([
        ("Mobil", "POST /sessions/refresh { refresh_token: T1 }"),
        ("auth-service", "T1.used_at boş mu?"),
        ("EVET → normal akış", "T2 üret, T1.used_at = now(), sebep = ROTATED, T2 döner"),
        ("HAYIR → alarm", "T1 zaten kullanılmış: ya tekrar oynatma ya hırsızlık"),
        ("auth-service", "family_id'nin TAMAMINI iptal et (REUSE_DETECTED) → 401"),
    ]),
    note(
        "<b>Rotasyonun tek amacı budur.</b> Yalnızca 'eskiyi iptal et' demek yetmez; asıl "
        "soru, iptal edilmiş bir token tekrar sunulduğunda ne olduğudur. Aile bazlı iptal "
        "olmadan saldırgan çaldığı token'la sessizce yenilemeye devam eder ve rotasyon "
        "hiçbir şey kazandırmaz."
    ),
]

story += [
    PageBreak(),
    Paragraph("5.3 Hesap silme ve servisler arası zincir", S_H2),
    body(
        "Silme için <b>token yetmez, parola da istenir</b>: çalınmış bir token'la geri "
        "dönüşü olmayan bir işlem yapılabilmesi kabul edilemez. Google Play de hesap açan "
        "her uygulamanın silme yolu sunmasını zorunlu tutuyor."
    ),
    FlowDiagram([
        ("Mobil", "DELETE /v1/auth/account { password }"),
        ("auth-service", "Parolayı doğrula → users satırını sil + outbox'a AccountDeleted"),
        ("PostgreSQL", "CASCADE: verification_codes ve refresh_tokens otomatik silinir"),
        ("email-worker", "Önce yayılım: user-service'e DELETE /internal/users/{id}"),
        ("user-service", "processed_events'e yaz + profiles satırını sil (tekrara dayanıklı)"),
        ("email-worker", "Sonra bilgilendirme e-postası gönder, published_at yazar"),
    ]),
    note(
        "<b>Sıra neden böyle:</b> önce diğer servise haber, sonra e-posta. Ters sırada "
        "olsaydı ve yayılım başarısız olsaydı, satır yeniden denenirken e-posta ikinci kez "
        "giderdi. Bu sırada ise yayılımın tekrarı zararsız, çünkü karşı taraf tekrara "
        "dayanıklı."
    ),
    Spacer(1, 2 * mm),
    body(
        "<b>auth-service, user_db'ye dokunmaz</b> (ADR 0005). Haberin servisler arasında "
        "taşınması gerekiyor. Phase 10'da bu bir HTTP çağrısı; Phase 11'de Kafka olayına "
        "dönüşecek ve <b>user-service'in silme mantığı değişmeyecek</b> — yalnızca "
        "tetikleyicisi değişecek."
    ),
]

# =============================================================================
# 6. Güvenlik
# =============================================================================
story += [
    PageBreak(),
    Paragraph("6. Güvenlik kararları", S_H1),
    body("<b>Hesap sayımı koruması</b> — kayıt ve giriş yanıtları, bir adresin sistemde olup olmadığını ele vermez."),
    body("<b>Sabit zamanlı giriş</b> — kullanıcı bulunamadığında da sahte bir bcrypt doğrulaması çalışır; yoksa yanıt süresindeki fark adresin varlığını ele verirdi."),
    body("<b>Kod ve token düz metin saklanmaz</b> — kod bcrypt, yenileme token'ı SHA-256 ile özetlenir. Veritabanı sızsa bile saldırgan hesap doğrulayamaz ya da oturum açamaz."),
    body("<b>X-User-Id enjeksiyon koruması</b> — arka servisler kimliği bu başlıktan okur ve kendileri doğrulamaz. Gateway başlığı gelen istekten <b>her zaman siler</b>, sonra doğruladığı değeri yazar. O satır olmasaydı istemci istediği kullanıcı gibi davranabilirdi."),
    body("<b>Hız sınırlama</b> — Redis ile e-posta ve IP başına. Geliştirmede docker-compose'dan gevşetildi; koddaki varsayılanlar üretim değerleridir."),
    Spacer(1, 3 * mm),
    Paragraph("Bilinen eksikler", S_H2),
    body("• <b>Otomatik test yok</b> — yalnızca güvenlik birim testleri var. Rotasyon, kod sayacı ve yanıt eşitliği elle doğrulandı; bu bir regresyon testi değildir."),
    body("• <b>Veri temizliği yok</b> — süresi geçmiş token'lar, tüketilmiş kodlar ve yayınlanmış outbox satırları sonsuza kadar birikiyor."),
    body("• <b>Ölü mektup görünürlüğü yok</b> — beş denemede vazgeçilen bir olay için uyarı üretilmiyor. Phase 12 (gözlemlenebilirlik) kapsamında çözülecek."),
]

build("auth-service.pdf", "auth-service",
      "Kimlik doğrulama servisi · auth_db · Phase 10", story)
