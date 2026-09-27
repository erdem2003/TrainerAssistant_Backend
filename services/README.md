# services — Backend

ADR 0005 uyarınca **database-per-service**; hiçbir servis başkasının veritabanına
dokunmaz. ADR 0006 uyarınca servisler arası asenkron akış **Kafka + outbox**.

| Servis | Port | Veritabanı | Ne yapıyor |
|---|---|---|---|
| `api-gateway` (nginx) | **18080** | — | Tek dış kapı; kimlik doğrular, `X-User-Id` yazar |
| `auth-service` | 18001 | `auth_db` | Kayıt, doğrulama kodu, token rotasyonu, hesap silme |
| `user-service` | 18002 | `user_db` | Profil (kilo, boy, yaş, günlük hedef) |
| `workout-service` | 18003 | `workout_db` | Antrenman kaydı, günlük program, istatistik, egzersiz kataloğu |
| `health-service` | 18004 | `health_db` | Su ve uyku takibi (ADR 0010) |
| `analytics-service` | 18005 | `analytics_db` | Kafka'dan beslenen antrenman projeksiyonu |

Ayrıca üç arka plan işçisi (ayrı konteyner, aynı imaj):

| İşçi | Ne yapıyor |
|---|---|
| `workout-outbox-relay` | `outbox` tablosundan Kafka'ya yayınlar |
| `analytics-consumer` | `workout.session` konusunu tüketip `workout_facts`'e yazar |
| `auth-email-worker` | Doğrulama kodu e-postalarını gönderir |

Sözleşme kuralları (URL, hata biçimi, idempotency, sayfalama, event şeması) ayrı bir
belgede tutuluyor ve **bu depoda yok**; aşağıdaki bölümler o kuralların uygulamadaki
karşılığını anlatıyor.

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
| **api-gateway (tek dış kapı)** | http://localhost:18080 |
| Servisler (doğrudan, geliştirme) | 18001–18007 |
| API dokümanı | `http://localhost:<port>/docs` |
| Postgres | `localhost:15433` |
| Redis | `localhost:16380` |
| Redpanda (Kafka API) | `localhost:19092` |

**Portlar yalnızca geliştirme için dışarı açık.** Üretimde tek giriş gateway olur;
`docker-compose.yml`'deki `ports:` blokları kaldırılır. Testler bu yayınlara
dayanıyor (aşağıda).

**E-posta gerçekten gönderiliyor.** `.env` içindeki `SMTP_*` değerleri Gmail'e
bağlanıyor; `SMTP_PASSWORD` bir uygulama şifresi ve **depoya girmez**.

### Sağlık kontrolü

```bash
curl localhost:18080/health/live                  # gateway ayakta mı
for p in 18001 18002 18003 18004 18005 18006 18007; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" localhost:$p/health/ready
done
```

`/health/live` bağımlılık kontrol etmez (süreç ayakta mı), `/health/ready`
veritabanını yoklar. Ayrım bilinçli: yeniden başlatma kararı ile trafik alma
kararı aynı şey değil.

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

## workout-service

En yüklü servis. Üç ayrı sorumluluk taşıyor ve hepsi aynı `workout_db`'de:

| Alan | Uçlar |
|---|---|
| Antrenman kaydı | `POST /v1/workouts`, `GET /v1/workouts`, `GET /v1/workouts/{id}` |
| Günlük program | `GET|PUT /v1/plan`, `GET /v1/plan/range` |
| İstatistik | `GET /v1/stats/daily` |

### Idempotent yükleme

Mobil taraf ağ hatasında yüklemeyi **tekrar deniyor**. Bu ancak sunucu aynı `id`'yi
ikinci kez gördüğünde yeni kayıt açmazsa güvenli:

- Aynı `id`, **aynı içerik** → `200` (çakışma değil; sonuç istenen durumla aynı)
- Aynı `id`, **farklı içerik** → `409`

`409` dönmek ilk durumda mobil senkron kuyruğunu kilitlerdi.

### Tamamlanma saklanmaz, türetilir

`plan_items` tablosunda "yapıldı" diye bir kolon **yok** (ADR 0012).
Her istekte `reps` satırlarından sayılıyor. Saklansaydı kullanıcı hedefini 10'dan
30'a çıkardığında eski "tamamlandı" işareti kalır ve yapmadığı bir programı
yapılmış görürdü.

### Gün sınırı saat dilimine göre

`workouts.started_at` UTC; kullanıcı yerel günde yaşıyor. İstemci `tz_offset`
(dakika) gönderiyor, sunucu **yarı açık UTC aralığına** çeviriyor `start, end)`.
Çevrim yapılmasaydı İstanbul'da gece 01:00'de yapılan antrenman düne yazılırdı.

İki tuzak koda yorum olarak yazılı:
- `timestamptz::date` Postgres'in **oturum** saat dilimine bağlanır → önce
  `AT TIME ZONE 'UTC'`
- asyncpg `interval` parametresini `timedelta`'dan kodlar; `'180 minutes'` metni
  parametre kodlamasında patlar

### Kartezyen tuzağı

`sets` ve `reps` tek JOIN'de toplansaydı her set süresi kendi tekrar sayısı kadar
tekrarlanır ve `active_seconds` kat kat şişerdi — **hata mesajı olmadan**. Set ve
tekrar granülariteleri ayrı CTE'lerde toplanıyor.

---

## health-service

Su ve uyku ([ADR 0010). Basit CRUD
ama iki ayrım önemli:

**Su: ekle ≠ ayarla.** `POST` birikimli ("200 ml daha içtim" doğası gereği toplanır,
aynı isteği iki kez göndermek 400 ml demek ve bu **doğru**). `PUT` doğrudan ayarlar
ve idempotent — yanlış sayılan miktarı geri çekmenin yolu.

**Uyku: `null` ≠ `0`.** Kayıt yoksa `minutes: null` döner, `0` değil. Sıfır "hiç
uyumadım", null "girmedim" demek ve ortalama hesabında farklı davranmaları gerekiyor
— `SleepInsights`'ın uyku–antrenman karşılaştırması bunun üstüne kurulu.

---

## analytics-service + olay akışı

```
workout-service                          analytics-service
  ┌──────────────────────┐
  │ TEK TRANSACTION      │
  │  workouts   INSERT   │
  │  outbox     INSERT   │
  └──────────┬───────────┘
             │  outbox-relay (yoklama)
             ▼
        Kafka  workout.session          ┌──────────────────┐
             ├──────────────────────────▶ consumer         │
             │  key = user_id           │  processed_events│
             │  (sıra garantisi)        │  workout_facts   │
             └──────────────────────────└──────────────────┘
```

**Neden outbox.** Olay doğrudan Kafka'ya yazılsaydı commit ile publish arasında
düşen bir süreç kalıcı veri kaybı bırakırdı. İkisi aynı transaction'da: kayıt varsa
olay da var.

**Neden idempotent consumer.** Kafka en az bir kez teslim ediyor. `processed_events`
tablosu aynı `event_id`'yi ikinci kez işlemeyi engelliyor.

**Neden `ON CONFLICT DO UPDATE`, `DO NOTHING` değil.** Replay sırasında satırlar
zaten var; `DO NOTHING` olsaydı yeniden oynatma hiçbir şey değiştirmezdi. Replay'in
anlamı tam olarak "aynı olaydan güncel mantıkla yeniden üret".

**Neden `workout_facts` gün bazında toplanmıyor.** Yazma anında kullanıcının saat
dilimi bilinmiyor; gün etiketi okuma anında `tz_offset` ile hesaplanıyor.

### Replay

```bash
# Tüketici grubunu sil, REPLAY_MODE=true ile baştan oynat
docker compose exec redpanda rpk group delete analytics-workout-v1
REPLAY_MODE=true docker compose up analytics-consumer
```

`REPLAY_MODE` `processed_events` kontrolünü atlar — normal çalışmada tekrarı yutmak
isteniyor, replay'de yeniden işlemek.

### Akış sağlığı

```bash
# Tüketici gecikmesi 0 olmalı
docker compose exec redpanda rpk group describe analytics-workout-v1

# Yayınlanmamış / hatalı outbox satırı olmamalı
docker compose exec postgres psql -U trainer -d workout_db -c \
  "SELECT count(*) FILTER (WHERE published_at IS NULL) AS bekleyen,
          count(*) FILTER (WHERE last_error IS NOT NULL) AS hatali FROM outbox;"
```

---

## Test

Testler **host'tan, çalışan yığına HTTP atarak** koşuyor:

```bash
cd services
pytest
```

**Neden mock değil gerçek Postgres.** Bu servislerin değerinin çoğu SQL'de: gün
sınırı hesabı, kartezyen tuzağı, `ON CONFLICT` davranışı, idempotency. Mock'lanan
bir veritabanı tam da bu hataları **gizler**. Geliştirme sırasında elle bulunan üç
hata da (asyncpg `interval` kodlaması, `timestamptz::date`'in oturum saat dilimine
bağlanması, `SUM`'ın kartezyene düşmesi) ancak gerçek Postgres'te görünürdü.

**Neden konteyner içinden değil.** İmajlar yalnızca çalışma bağımlılıklarını
kuruyor; `pytest` `dev` extras'ta ve imajda yok.

**Tablolar temizlenmiyor.** Bu veritabanlarında **gerçek kullanıcı verisi** var.
`TRUNCATE` yerine her test rastgele bir `user_id` üretiyor; temizlik yalnızca o
kullanıcının satırlarını siliyor. Silme sırası önemli — önce `outbox` (yayınlanmamış
olay hiç gitmesin), sonra kaynak tablolar, en son `analytics_db` **yoldaki olaylar
inene kadar yoklanarak**.

Kapsanan davranışlar:

| Servis | Ne doğrulanıyor |
|---|---|
| `workout` | Aynı id iki kez → tek kayıt; farklı içerik → 409; içerik özeti sıra bağımsız |
| `workout` | Gece 01:00 antrenmanı bugüne düşüyor; aynı antrenman `tz_offset=0` ile düne |
| `workout` | Hedef değişince tamamlanma kendiliğinden değişiyor; hedefin üstü kırpılmıyor |
| `workout` | `active_seconds` kartezyene düşmüyor; dinlenme aktif süreye girmiyor |
| `health` | Ekle ≠ ayarla; uyku `null` ≠ `0`; 20 L üst sınırında kırpma |
| `analytics` | Uçtan uca Kafka akışı; tekrarlanan olay yeniden işlenmiyor; kayıt çoğaltmıyor |
| `auth` | Token rotasyonu; **yeniden kullanımda ailenin tamamı düşüyor**; hız sınırı |

---

## Sırada

- **Observability (Phase 12)** — OpenTelemetry, Prometheus, Kafka sınırını geçen trace
- **`auth` fanout'unun Kafka'ya taşınması** — hesap silme hâlâ elle yazılmış listeden HTTP ile gidiyor
- **`/v1/analytics/daily`'nin gateway'de yayınlanması** — günlük toplamları hâlâ `workout-service` veriyor; ikisini birden açmak aynı sayı için iki kaynak demekti
- **Kubernetes + CI/CD (Phase 13)**
