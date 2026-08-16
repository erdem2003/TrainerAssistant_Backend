# -*- coding: utf-8 -*-
"""user-service PDF'ini üretir. Çalıştırma: python docs/build_user_pdf.py"""

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
        "<b>user-service</b>, kullanıcının <b>kim olduğunu değil, nasıl biri olduğunu</b> "
        "tutar: vücut ölçüleri, hedefi, birim tercihi ve kişisel kalibrasyon verisi. "
        "ADR 0005'teki tanımı şudur — <i>kullanıcı profili: ölçüler, kalibrasyon, tercihler</i>."
    ),
    body(
        "Parola, token ve e-posta doğrulama burada <b>yoktur</b>; onların sahibi "
        "auth-service'tir. Bu servis kimlik doğrulaması da yapmaz: gateway JWT'yi zaten "
        "doğrular ve kimliği <font face='Courier'>X-User-Id</font> başlığında iletir."
    ),
    note(
        "<b>Neden ayrı bir servis:</b> profil verisi neredeyse her ekranda okunur, "
        "kimlik bilgisi ise 30 günde bir. Erişim profilleri ve hassasiyet sınıfları "
        "tamamen farklı. Ayrıca ikisi ayrı olduğunda auth-service ileride yönetilen bir "
        "kimlik sağlayıcıyla değiştirilebilir ve bu servis etkilenmez."
    ),
    Paragraph(
        "Veritabanı: <font face='Courier'>user_db</font> &nbsp;·&nbsp; "
        "Port: 8002 (konteyner içinde 8000)", S_SMALL,
    ),
]

# =============================================================================
# 2. Tablolar
# =============================================================================
story += [Paragraph("2. Veritabanı tabloları", S_H1)]

story.append(schema_table(
    "profiles",
    "Kullanıcı profili. Birincil anahtar, auth-service'in ürettiği user_id ile aynıdır.",
    [
        ("user_id", "uuid", "PK — auth_db'deki users.id ile aynı değer. Ayrı id üretilmez"),
        ("sex", "text", "FEMALE | MALE | UNSPECIFIED. NULL = henüz sorulmadı"),
        ("age", "integer", "13–120 arası. Doğum tarihi değil (bkz. 5.4)"),
        ("weight_kg", "real", "20–350. Her zaman kilogram"),
        ("height_cm", "real", "80–260. Her zaman santimetre"),
        ("goal", "text", "MUSCLE_GAIN | FAT_LOSS_HIIT | FAT_LOSS_CARDIO | FUNCTIONAL"),
        ("unit_system", "text", "METRIC | IMPERIAL. Yalnızca gösterimi etkiler"),
        ("daily_goal_reps", "integer", "1–1000, varsayılan 20"),
        ("onboarding_completed_at", "timestamptz", "NULL ise kişiselleştirme akışı bitmedi"),
        ("created_at", "timestamptz", ""),
        ("updated_at", "timestamptz", ""),
    ],
))
story.append(note(
    "<b>Bu tablonun users'a yabancı anahtarı YOKTUR — olamaz da.</b> "
    "<font face='Courier'>users</font> başka bir veritabanında "
    "(<font face='Courier'>auth_db</font>) ve ADR 0005 hiçbir servisin başkasının "
    "veritabanına dokunmamasını şart koşuyor. Referans bütünlüğü veritabanı seviyesinde "
    "kurulamıyor; olay akışıyla (AccountDeleted) sağlanıyor. Bu, dağıtık mimarinin "
    "bilinçli olarak kabul edilmiş bedelidir."
))

story.append(schema_table(
    "processed_events",
    "İşlenmiş olayların kaydı. Aynı olayın iki kez işlenmesini engeller.",
    [
        ("event_id", "uuid", "PK — auth-service'in outbox.id değeri"),
        ("event_type", "text", "AccountDeleted, …"),
        ("processed_at", "timestamptz", "İndeksli; ileride eski kayıtları temizlemek için"),
    ],
))

story.append(schema_table(
    "schema_migrations",
    "Uygulanmış migration'lar. Her servis kendi migration'ını taşır (ADR 0005).",
    [("version", "text", "PK — 001_initial, 002_age_instead_of_birth_date"),
     ("applied_at", "timestamptz", "")],
))

# =============================================================================
# 3. İlişkiler
# =============================================================================
story += [
    PageBreak(),
    Paragraph("3. Tablolar arası ilişki", S_H1),
    body(
        "Bu servisin <b>veritabanı içinde hiçbir yabancı anahtarı yoktur</b>. İki tablo "
        "birbirinden bağımsızdır ve ilişki <b>veritabanı sınırının dışında</b>, servisler "
        "arasında kurulur."
    ),
    Spacer(1, 4 * mm),
    Relations(
        root="auth_db · users",
        children=[("profiles", "user_id (mantıksal)"),
                  ("processed_events", "olay kaydı")],
        detached=[("schema_migrations", "— altyapı tablosu, ilişkisiz")],
    ),
    Spacer(1, 4 * mm),
    body(
        "Yukarıdaki ok <b>mantıksal</b> bir bağdır, veritabanı kısıtı değildir. "
        "<font face='Courier'>profiles.user_id</font> ile "
        "<font face='Courier'>users.id</font> aynı değeri taşır ama PostgreSQL bunu "
        "zorlayamaz — iki farklı veritabanındadırlar."
    ),
    note(
        "<b>Bunun pratik sonucu:</b> auth_db'deki bir kullanıcı, API kullanılmadan "
        "doğrudan SQL ile silinirse user_db'de <b>yetim bir profil</b> kalır. Geliştirme "
        "sırasında bu bir kez yaşandı ve zincirin neden gerekli olduğunu gösterdi: "
        "bütünlüğü koruyan şey yabancı anahtar değil, olay akışıdır."
    ),
]

# =============================================================================
# 4. Uçlar
# =============================================================================
story += [
    Paragraph("4. API uçları", S_H1),
]

_rows = [["Uç", "Yanıt", "Ne yapar"]]
for _ep, _st, _desc in [
    ("GET /v1/users/me", "200", "Profili oku. Satır yoksa boş profil döner, 404 değil"),
    ("PUT /v1/users/me", "200", "Profili tam olarak yaz (upsert)"),
    ("DELETE /internal/users/{id}", "204", "Hesap silindiğinde profili temizler (dahili)"),
    ("GET /health/live", "200", "Süreç ayakta mı"),
    ("GET /health/ready", "200", "Veritabanı erişilebilir mi"),
]:
    _rows.append([
        Paragraph(f'<font face="Courier" size="7.5">{_ep}</font>', S_CELL),
        Paragraph(_st, S_CELL),
        Paragraph(_desc, S_CELL),
    ])

_t = Table(_rows, colWidths=[62 * mm, 14 * mm, 92 * mm], repeatRows=1)
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
story += [_t, Spacer(1, 2 * mm)]
story.append(note(
    "<font face='Courier'>/internal/…</font> uçları <b>gateway'de tanımlı değildir</b> ve "
    "dışarıdan erişilemez; yalnızca Docker ağı içinden, auth-service'in worker'ı "
    "tarafından çağrılır. İkinci savunma hattı olarak paylaşılan bir anahtar "
    "(<font face='Courier'>X-Internal-Key</font>) da isteniyor."
))

# =============================================================================
# 5. Akışlar
# =============================================================================
story += [
    PageBreak(),
    Paragraph("5. Sistem nasıl çalışır", S_H1),

    Paragraph("5.1 Profil satırı tembel oluşturulur", S_H2),
    body(
        "Klasik yaklaşım, auth-service'in <font face='Courier'>UserRegistered</font> "
        "olayını yayınlaması ve bu servisin onu dinleyip boş bir profil satırı açmasıdır. "
        "<b>Bu tasarım onu kullanmıyor.</b>"
    ),
    FlowDiagram([
        ("Mobil", "GET /v1/users/me (Authorization: Bearer …)"),
        ("api-gateway", "JWT'yi doğrular, X-User-Id başlığını kendisi yazar"),
        ("user-service", "Satır var mı? Yoksa 200 + tüm alanlar null (404 DEĞİL)"),
        ("Mobil", "PUT /v1/users/me — kişiselleştirme akışının sonunda TEK çağrı"),
        ("user-service", "UPSERT: satır ilk yazımda doğar"),
    ]),
    note(
        "<b>Kazanç:</b> 'kayıt oldu ama profili henüz yok' penceresi hiç oluşmaz. Olay "
        "tabanlı kurulumda bu pencere gerçektir ve istemcinin onu ayrıca ele alması "
        "gerekirdi. Kimliğin geçerliliğini sormaya da gerek yok: gateway JWT'yi zaten "
        "doğruladı, yani <font face='Courier'>X-User-Id</font> güvenilir."
    ),
    Spacer(1, 2 * mm),
    body(
        "<b>404 yerine boş profil dönmesi</b> de aynı mantığın parçası: profili olmayan "
        "kullanıcı bir hata durumu değil, normal ilk hâldir. 404 dönmek istemcide her "
        "ekranda özel bir dallanma gerektirirdi."
    ),
]

story += [
    PageBreak(),
    Paragraph("5.2 Kişiselleştirme akışı ve kapı", S_H2),
    body(
        "Giriş, kayıt doğrulama, parola sıfırlama ve uygulamanın soğuk açılışı — dördü de "
        "aynı soruyu sorar: bu kullanıcı profilini doldurdu mu? Cevabı tek bir yerde, "
        "mobil taraftaki <b>kapı ekranı</b> verir."
    ),
    FlowDiagram([
        ("Mobil (kapı)", "GET /v1/users/me"),
        ("onboarding_completed_at NULL", "Kişiselleştirme: splash → cinsiyet → kilo → boy → yaş → hedef"),
        ("Mobil", "PUT /v1/users/me { …, onboarding_completed: true }"),
        ("user-service", "Zaman damgasını SUNUCU koyar; istemci saatine güvenilmez"),
        ("onboarding_completed_at DOLU", "Doğrudan Feed ekranı"),
    ]),
    note(
        "<b>Ağ yoksa Feed'e geçilmez.</b> Profilin dolu olup olmadığı bilinmiyorsa "
        "varsayıp geçmek, profilini doldurmamış kullanıcıyı boş bir ekranda bırakırdı. "
        "Onun yerine 'tekrar dene' gösterilir."
    ),
    Spacer(1, 2 * mm),
    Paragraph("5.3 Neden PUT (tam değiştirme), PATCH değil", S_H2),
    body(
        "Kişiselleştirme akışı beş ekranı <b>tek seferde</b> yazar; profil ekranı da "
        "elindeki tam değerlerle yazar. Kısmi güncelleme, 'alan gönderilmedi mi yoksa "
        "null'a mı çekilmek isteniyor' ayrımını gerektirir — bu ekranların hiçbirinde "
        "böyle bir ihtiyaç yok. Sonuç: uç doğal olarak tekrara dayanıklıdır, ayrı bir "
        "idempotency anahtarı gerekmez."
    ),
    body(
        "<font face='Courier'>onboarding_completed_at</font> bir istisnadır: "
        "<font face='Courier'>COALESCE</font> ile <b>bir kez yazılır, sonra korunur</b>. "
        "Kullanıcı profilini sonradan düzenlediğinde akışın tamamlanma tarihi "
        "değişmemeli; son düzenleme zamanı için <font face='Courier'>updated_at</font> var."
    ),
]

story += [
    PageBreak(),
    Paragraph("5.4 Ölçüler, birimler ve türetilmiş değerler", S_H2),
    body(
        "<b>Veritabanında ölçüler her zaman metriktir</b> (kg, cm). "
        "<font face='Courier'>unit_system</font> yalnızca bir <b>gösterim tercihidir</b>. "
        "Sayıyı kullanıcının seçtiği birimde saklayıp yanına bir bayrak koymak, her "
        "tüketiciye dönüşüm yükler ve er geç biri unutur."
    ),
    body(
        "<b>Vücut kitle endeksi saklanmaz, okunurken hesaplanır.</b> Boy ve kilonun saf "
        "bir fonksiyonudur; saklandığı anda kilo güncellenince bayat kalır. Hesap mobil "
        "tarafta, <font face='Courier'>core/health/HealthMetrics.kt</font> içinde yapılır."
    ),
    note(
        "<b>Yaş, doğum tarihi değil — bilinen bedeliyle.</b> Yaş zamanla bayatlar: 25 "
        "yazan kullanıcı bir yıl sonra hâlâ 25 görünür. Doğum tarihi bu sorunu tanımı "
        "gereği yaşamazdı. Tercih bilinçli yapıldı: kişiselleştirme akışında yaş sormak "
        "tek bir tekerlek hareketi, doğum tarihi ise takvim seçici gerektiriyordu. "
        "İleride tarihe dönülmek istenirse mevcut yaş değerlerinden tarih geri "
        "üretilemez; kullanıcılara yeniden sormak gerekir."
    ),
    Spacer(1, 2 * mm),
    Paragraph("5.5 Hesap silme: tekrara dayanıklı tüketici", S_H2),
    FlowDiagram([
        ("auth-service worker", "DELETE /internal/users/{id}, başlıkta X-Event-Id"),
        ("user-service", "processed_events'e INSERT … ON CONFLICT DO NOTHING"),
        ("İlk kez ise", "profiles satırını sil — ikisi de AYNI transaction'da"),
        ("Tekrarsa", "İşi atla ama yine 204 dön"),
    ]),
    note(
        "Olay teslimi <b>en az bir kez</b> garantisi verir (ADR 0006): aynı olay iki kez "
        "gelebilir. Tekrarda hata dönmek, gönderen tarafın satırı sonsuza kadar yeniden "
        "denemesine yol açardı. Kayıt ve silme aynı transaction'da olmalı; ayrı olsalardı "
        "kayıt yazılıp silme başarısız olduğunda olay 'işlendi' sayılır ve profil sonsuza "
        "kadar kalırdı."
    ),
]

# =============================================================================
# 6. Kararlar ve eksikler
# =============================================================================
story += [
    PageBreak(),
    Paragraph("6. Tasarım kararları ve bilinen eksikler", S_H1),
    Paragraph("Bilinçli olarak yapılmayanlar", S_H2),
    body("• <b>Redis yok</b> — hız sınırlama gateway'de. Profil uçları kaba kuvvet hedefi değil; Redis eklemek bakımı olan ama karşılığı olmayan bir bağımlılık olurdu."),
    body("• <b>Kalibrasyon tablosu yok</b> — servisin sınırlarına dahil ama bilgisayarlı görü tarafının eşik biçimi henüz oturmadı (<font face='Courier'>tuning_status: initial</font>). Oturmamış bir veri için şema açmak, doldurulmayan bir iskelet üretirdi."),
    body("• <b>UserRegistered olayı dinlenmiyor</b> — tembel oluşturma sayesinde gerekmiyor (bkz. 5.1). Zorunlu tek olay AccountDeleted'dır."),
    Spacer(1, 3 * mm),
    Paragraph("Eksikler", S_H2),
    body("• <b>Hiç otomatik test yok.</b> Uçlar elle (curl ile) doğrulandı: boş profil, yazma/okuma, doğrulama sınırları, silme zinciri ve tekrar koruması. Bunların hiçbiri regresyon testi değil."),
    body("• <b>processed_events temizlenmiyor</b> — tablo sonsuza kadar büyür. Temizlik için indeks eklendi ama işin kendisi yazılmadı."),
    body("• <b>Yetim profil tespiti yok</b> — olay kaybolursa profil sessizce kalır ve kimse fark etmez."),
]

build("user-service.pdf", "user-service",
      "Kullanıcı profili servisi · user_db · Phase 10", story)
