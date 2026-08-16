# services — Backend

Phase 10. ADR 0005 uyarınca **database-per-service**; hiçbir servis başkasının
veritabanına dokunmaz.

| Servis | Durum | Port | Veritabanı |
|---|---|---|---|
| `api-gateway` (nginx) | ✅ çalışıyor | **8080** | — |
| `auth-service` | ✅ çalışıyor | 8001 | `auth_db` |
| `user-service` | ⬜ | 8002 | `user_db` |
| `workout-service` | ⬜ | 8003 | `workout_db` |
| `analytics-service` | ⬜ | 8004 | `analytics_db` |

Sözleşme kuralları (URL, hata biçimi, idempotency, sayfalama, event şeması):
`.claude/skills/service-contract/SKILL.md`

---

## Çalıştırma

```bash
cd services
cp .env.example .env
./infra/generate-keys.sh      # JWT için RSA çifti (depoya girmez)
docker compose up --build
```

| Ne | Nerede |
|---|---|
| **api-gateway (tek dış kapı)** | http://localhost:8080 |
| auth-service (doğrudan, geliştirme) | http://localhost:8001 |
| API dokümanı | http://localhost:8001/docs |
| **Mailpit gelen kutusu** | http://localhost:8025 |
| Postgres | `localhost:5433` (kullanıcı/parola: `trainer`) |
| Redis | `localhost:6380` |

**Gerçek e-posta gönderilmez.** Yerel geliştirmede Mailpit tüm mailleri yakalar;
doğrulama kodları tarayıcıdan okunur.

---

## Teknoloji kararları

**ORM yok, ham SQL.** Sorgular `app/repo/*.py` içinde modül başında sabit olarak
duruyor. Ne çalıştığı gözden geçirilebilsin diye — ORM'in ürettiği SQL'i tahmin
etmek yerine SQL'in kendisi kodda.

**Alembic yok.** Migration'lar `migrations/` altında numaralı `.sql` dosyaları,
uygulananlar `schema_migrations` tablosunda. ADR 0005'in "her servis kendi
migration'ını taşır" kuralı araçla değil kuralla sağlanıyor. Migration'lar açılışta
otomatik koşuyor.

**asyncpg + FastAPI + Pydantic v2.** `uv` ile paketleme — Docker katman
önbelleğiyle yeniden derleme saniyeler sürüyor.

---

## api-gateway (nginx)

Tek dış kapı. Dört işi var:

| İş | Nasıl |
|---|---|
| Yönlendirme | `/v1/auth/*` → auth-service |
| Correlation ID | gelen değer korunur, yoksa üretilir |
| Kaba hız sınırı | auth uçlarında 10r/dk, diğerlerinde 120r/dk |
| **`X-User-Id` enjeksiyonunu engelleme** | `proxy_set_header X-User-Id "";` |

Sonuncusu güvenlik açısından en kritiği. Arka servisler kimliği `X-User-Id`
başlığından okuyup **kendileri tekrar doğrulamıyor** (service-contract §2).
İstemcinin bu başlığı göndermesine izin verilseydi **herkes istediği kullanıcı
olabilirdi.** Gateway başlığı her istekte siliyor, sonra kendisi yazıyor.

**JWT imza doğrulaması henüz yok.** Nginx'in kendisi RS256 doğrulayamaz.
`auth_request` deseni `conf.d/gateway.conf` içinde hazır ve yorumlu duruyor;
`/v1/auth/introspect` ucu yazılınca açılacak. Üçüncü parti nginx modülü derlemek
yerine bu tercih edildi — standart imaj korunuyor ve doğrulama mantığı anahtarın
zaten bulunduğu yerde, auth-service'te kalıyor.

## auth-service

### Uçlar

```
POST   /v1/auth/registrations          kayıt          → 202 (her zaman)
POST   /v1/auth/registrations/verify   kod doğrula    → 200 + token çifti
POST   /v1/auth/registrations/resend   yeni kod       → 202
POST   /v1/auth/sessions               giriş          → 200 + token çifti
POST   /v1/auth/sessions/refresh       yenileme       → 200 + yeni çift
DELETE /v1/auth/sessions               çıkış          → 204

POST   /v1/auth/password-resets         sıfırlama kodu iste → 202
POST   /v1/auth/password-resets/confirm kod + yeni parola   → 200 + token çifti
PUT    /v1/auth/password        🔒      parola değiştir     → 200 + token çifti
DELETE /v1/auth/account         🔒      hesabı sil          → 204

GET    /v1/auth/me              🔒      oturumdaki kullanıcı
GET    /v1/auth/introspect      (dahili) gateway'in doğrulama alt-isteği
GET    /health/live · /health/ready
```

🔒 = geçerli access token zorunlu (gateway `auth_request` ile doğrular)

> `service-contract` §1 "yolda fiil olmaz" der. Kimlik doğrulama bunun kabul
> edilmiş istisnası — OAuth2 de `/token`, `/revoke` kullanır. Oturum bir kaynak
> olarak modellendi: `POST /sessions` oluşturur, `DELETE /sessions` sonlandırır.

### Token

| | Tür | Süre | Saklama |
|---|---|---|---|
| Access | JWT **RS256** | 15 dk | saklanmaz |
| Refresh | opak, 32 bayt | 30 gün | SHA-256 hash, DB'de |

**Refresh neden JWT değil:** iptal edilebilir olmak zorunda. Stateless bir JWT'yi
iptal etmek için kara liste gerekir — o da DB sorgusu demektir, yani statelessness
hiçbir şey kazandırmadan kaybedilir.

**Neden RS256:** gateway yalnızca *public key* ile doğrular; private key auth'ta
kalır. Simetrik anahtar olsaydı gizli anahtarı her doğrulayan servisle paylaşmak
gerekirdi.

### Rotasyon ve yeniden kullanım tespiti

Bu servisin en önemli güvenlik özelliği. "Yenilemede eskisini iptal et" yaygın ama
**eksik** bir tariftir; asıl soru şudur: *zaten kullanılmış* bir refresh token
tekrar sunulursa ne olur?

```
refresh(T1) → T1 daha önce kullanıldı mı?
              ├─ hayır → T2 üret, T1 = ROTATED
              └─ EVET  → family_id'nin TAMAMINI iptal et (REUSE_DETECTED) → 401
```

Bu ya replay ya hırsızlıktır ve hangi kopyanın saldırganda olduğu bilinemez —
bu yüzden zincirin tamamı düşer, meşru token dahil. Bu kontrol olmadan saldırgan
çaldığı token'la sessizce yenilemeye devam eder ve rotasyon hiçbir şey kazandırmaz.

Eşzamanlı iki yenileme de aynı yola düşer: `mark_rotated` yalnızca
`used_at IS NULL` iken günceller, kaybeden istek yeniden kullanım sayılır.

### Kayıt — üç dal, tek yanıt

```
POST /v1/auth/registrations   →   HER ZAMAN 202

├─ e-posta yeni              → hesap aç, kod gönder
├─ e-posta var, DOĞRULANMAMIŞ → parolayı ÜZERİNE YAZ, yeni kod gönder
└─ e-posta var, DOĞRULANMIŞ   → hiçbir şey değişmez,
                                sahibine "biri kayıt olmaya çalıştı" maili
```

İkinci dal bir ürün gereksinimi: sahte bir adresle kayıt olan biri hesabı
doğrulayamaz, ve adresin gerçek sahibi geldiğinde "bu e-posta bekliyor" duvarına
çarpmamalı. `users.OVERWRITE_UNVERIFIED` sorgusundaki `email_verified_at IS NULL`
koşulu bunu doğrulanmamışlarla sınırlar — doğrulanmış bir hesabın parolası bu
yolla asla değişemez.

Üç dal dışarıdan **ayırt edilemez**; aksi hâlde saldırgan hangi e-postaların
kayıtlı olduğunu öğrenirdi.

### Doğrulama kodu

6 hane (`secrets`, `random` değil), 10 dakika, **bcrypt ile hash'li**.

3 yanlış denemeden sonra kod geçersiz kılınır ve **otomatik yeni kod gönderilmez.**
Otomatik göndermek e-posta bombalamaya açık kapı bırakırdı: yanlış kod gir → yeni
mail → tekrarla. Kullanıcı "Tekrar gönder"e basmalı; o uç 60 sn bekleme + saatte 5
sınırıyla korunuyor.

### E-posta ve outbox

`smtplib` (standart kütüphane) kullanılıyor; bloklayıcı çağrı `asyncio.to_thread`
ile thread'e alınıyor. Worker bir arka plan süreci, istek yolunda değil.

**Gerçek gönderim için** `.env` içinde SMTP ayarlarını doldurun — Gmail için
uygulama şifresi (App Password) gerekir, normal hesap parolası kabul edilmez.
Adım adım talimat `.env.example` içinde.

E-posta doğrudan gönderilmez; kayıt işlemiyle **aynı transaction'da** `outbox`
tablosuna yazılır, ayrı bir worker süreci gönderir.

"Kullanıcı oluşturuldu ama mail gitmedi" (ya da tersi), iki farklı sisteme yazan
her serviste kaçınılmazdır. Outbox bunu tek transaction'a indirger.

Phase 11'de relay Kafka'ya publish etmeye başlayacak ve worker consumer olacak —
**outbox'a yazan kod hiç değişmeyecek.**

### Worker neden auth'un içinde — ve Phase 11'de nereye gidecek

E-posta göndermek **auth'un bounded context'i değil.** "Bir insana mesaj ilet"
yeteneğine ileride `workout` (seri hatırlatması), `analytics` (haftalık rapor) ve
`user` (hesap değişikliği) de ihtiyaç duyacak.

ADR 0005 ayrı bir `notification-service`'i **yasaklamıyor** — MVP'de reddedip
**Phase 11+ için planlıyor.** Şimdi ayırmıyoruz çünkü Kafka yok; topic olmadan iki
deployable arasında yalnızca doğrudan bağımlılık kurulabilirdi, o da daha kötü.

Kod taşınmayı bedava kılacak şekilde bölündü:

```
worker/mailer.py          event sözlüğü → mail.  VERİTABANINI BİLMEZ.
worker/outbox_worker.py   outbox → mailer        ← Phase 10, geçici
```

Phase 11'de:

```
auth-service/relay.py        outbox → Kafka topic
notification-service/        Kafka topic → mailer.py   (olduğu gibi taşınır)
```

**Event bir topic'ten geçtiği anda consumer'ın nerede koştuğu mimari değil,
dağıtım kararıdır.** Bağlantı zaten topic ile kopmuş olur.

### Hız sınırları

| İşlem | Sınır |
|---|---|
| giriş | e-posta başına 5/dk · IP başına 20/dk |
| kayıt | e-posta başına 3/saat · IP başına 10/saat |
| kod tekrar gönderme | 60 sn bekleme · e-posta başına 5/saat |

Redis düşerse sınırlar uygulanamaz ve **istek geçer** — kimlik doğrulamayı
tamamen durdurmak, hız sınırı kaybetmekten kötü bir arıza. Kritik kurallar
(3 deneme, 60 sn bekleme) ayrıca veritabanında da kontrol ediliyor.

---

## Test

```bash
# Birim testler
docker compose run --rm --user root --no-deps \
  -v "$PWD/auth-service/tests:/srv/tests:ro" auth-service \
  sh -c "uv pip install --system --no-cache -q pytest pytest-asyncio && cd /srv && python -m pytest tests -q"

# Uçtan uca senaryo
# tests/e2e.http dosyasını REST Client ile satır satır çalıştır
```

Doğrulanmış davranışlar:

- ✅ Kayıt → outbox → worker → Mailpit zinciri
- ✅ E-posta normalize ediliyor (`Test@Example.COM` → `test@example.com`)
- ✅ 3 yanlış denemede kod geçersiz, **yeni mail gönderilmiyor**
- ✅ 60 saniye bekleme kuralı (`Retry-After` başlığıyla)
- ✅ **Yeniden kullanım tespiti: aile iptal ediliyor**
- ✅ Bilinmeyen e-posta ve yanlış parola aynı hata, benzer süre
- ✅ Doğrulanmış hesaba kayıt denemesi hesabı değiştirmiyor

---

## Sırada

`api-gateway` (JWT doğrulama + `X-User-Id` yazımı) → `user-service` →
`workout-service` → `analytics-service`.
