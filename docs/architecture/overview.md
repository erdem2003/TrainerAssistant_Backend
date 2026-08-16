# Sistem Mimarisi — Genel Bakış

> Bu dosya sistemin **güncel** resmini tutar. Mimari değiştiğinde burası da güncellenir.
> Kararların gerekçeleri `adr/` altındadır.

---

## 1. Sistemin Özeti

Kullanıcı telefonunu sabitler, kamera onu görür. Uygulama egzersizi analiz eder,
tekrarları sayar, form hatalarını tespit eder ve gerçek zamanlı sesli koçluk verir.

**Temel mimari ilke: analizin tamamı cihazda çalışır.** Backend sadece sayıları saklar
ve toplar. Görüntü hiçbir zaman cihazdan çıkmaz.

---

## 2. On-Device Pipeline (kalp)

```
   Kamera (CameraX, 30 FPS)
        │  ImageAnalysis · KEEP_ONLY_LATEST → ~15 FPS analiz
        ▼
   ML Kit Pose Detection                        ~30 ms/frame
        │  33 landmark + inFrameLikelihood
        ▼
   Normalization + Smoothing                    < 1 ms
        │  image-norm → One-Euro → hip-centered / torso-scaled
        ▼
   Feature Extraction                           < 1 ms
        │  elbow_angle, knee_angle, hip_vertical_offset, ...
        ▼
   ┌────────────────────────────────────────────────────┐
   │  Exercise Engine  (egzersizden bağımsız motor)     │
   │                                                    │
   │   Setup Validator  →  kurulum uygun mu?            │
   │   Rep FSM          →  faz sinyali p, histerezis    │
   │   Rule Engine      →  anlık form hataları          │
   │   [ML Classifier]  →  rep sonu kalite  (Phase 9+)  │
   └────────────────────────────────────────────────────┘
        │  RepCompleted · FormError · SetupIssue
        ▼
   Feedback Engine                              öncelik + cooldown
        │
        ├──► TextToSpeech        "Biraz daha aşağı in."
        └──► Compose UI          sayaç, skeleton overlay, skor
        │
        ▼
   Room (yerel, tek doğruluk kaynağı)
        │  sync kuyruğu — WorkManager, offline-first
        ▼
   Backend  (Phase 10+)
```

**Motor egzersizden bağımsızdır.** Push-up ve squat arasındaki tek fark, spec dosyalarından
okunan veridir (`docs/computer-vision/pushup.md`, `squat.md`). Yeni egzersiz eklemek
kod değil, spec yazmaktır.

---

## 3. Backend (Phase 10+)

```
                    Android
                       │  HTTPS
                       ▼
              ┌─────────────────┐
              │   api-gateway   │  routing · JWT doğrulama
              │   (stateless)   │  rate limit · correlation_id
              └────────┬────────┘
         ┌─────────────┼─────────────┬──────────────┐
         ▼             ▼             ▼              ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐
   │   auth   │  │   user   │  │ workout  │  │  analytics  │
   │ auth_db  │  │ user_db  │  │workout_db│  │analytics_db │
   └────┬─────┘  └────▲─────┘  └────┬─────┘  └──────▲──────┘
        │             │             │               │
        │ UserRegistered            │ WorkoutCompleted
        └─────────────┴─────────────┴───────────────┘
                       Kafka  (outbox pattern)
```

| Servis | Sorumluluk | DB |
|---|---|---|
| `api-gateway` | Tek public giriş, JWT doğrulama, rate limit, correlation ID | — |
| `auth-service` | Kimlik, JWT issue/refresh, iptal, hesap devralma (claim) | `auth_db` |
| `user-service` | Profil, vücut ölçüleri, **kalibrasyon verisi**, tercihler | `user_db` |
| `workout-service` | Oturum ingest, set/rep/hata kayıtları, geçmiş, egzersiz kataloğu | `workout_db` |
| `analytics-service` | Agregasyon, ilerleme trendi, yorgunluk analizi, rekorlar | `analytics_db` |

**Değişmez kurallar:**
- Hiçbir servis başka servisin veritabanına dokunmaz
- Servisler arası senkron çağrı minimumda; veri gerekiyorsa event ile replike edilir
- Her servis kendi migration'larını taşır

**Redis:** gateway'de rate limit · auth'ta refresh/iptal listesi · analytics'te read-model
cache · workout'ta idempotency key. Birincil veri deposu olarak kullanılmaz.

---

## 4. Veri Sınırı — Ne Nerede Kalır

| Cihazda kalır | Backend'e gider |
|---|---|
| Kamera görüntüsü, frame, bitmap — **her zaman** | Antrenman özeti (set, rep, süre) |
| Pose detection | Rep metrikleri (ROM, tempo, skor) |
| Feature extraction, rule engine, FSM | Tespit edilen form hataları |
| ML inference | Kullanıcı profili, kalibrasyon |
| Feedback üretimi ve TTS | *(opsiyonel, açık onayla)* landmark sekansları |

Görüntünün cihazdan çıkmaması bir gizlilik tercihi değil, **mimari kısıttır**. Bkz. ADR 0002.

---

## 5. Kimlik

İlk açılışta cihazda anonim `user_id` (UUID) üretilir. Giriş ekranı yoktur.
Kalibrasyon, antrenman geçmişi ve dataset bu id ile çalışır. Phase 10'da kullanıcı hesap
oluşturursa anonim profil devralınır — veri kaybı ve migration yoktur. Bkz. ADR 0007.

---

## 6. Henüz Kurulmayanlar

| Ne | Ne zaman | Neden şimdi değil |
|---|---|---|
| Backend servisleri | Phase 10 | Belirsiz olan iş (CV) önce yapılır |
| ML modeli | Phase 8 | Veri eşiği sağlanmadan model eğitilmez |
| Kafka | Phase 11 | Servisler ayakta olmadan event'in anlamı yok |
| OpenTelemetry / Grafana | Phase 12 | Tek servis varken distributed tracing anlamsız |
| Kubernetes | Phase 13 | Docker Compose yeterli olduğu sürece |
| Recommendation / Notification servisleri | Phase 11+ | Analytics verisi birikmeden önerecek bir şey yok |
| **Exercise servisi** | **hiç** | Statik, okuma-ağırlıklı veri — workout-service içinde modül. Bkz. ADR 0005 |

---

## 7. ADR Dizini

| # | Karar | Durum |
|---|---|---|
| [0001](adr/0001-rule-based-first-ml-later.md) | Önce rule-based, sonra ML | Kabul |
| [0002](adr/0002-on-device-analysis.md) | Tüm gerçek zamanlı analiz on-device | Kabul |
| [0003](adr/0003-rep-level-analysis-unit.md) | Analiz birimi frame değil rep | Kabul |
| [0004](adr/0004-torso-length-normalization.md) | Hip-centered + torso-length normalization | Kabul |
| [0005](adr/0005-microservice-boundaries.md) | 5 servis, database-per-service | Kabul |
| [0006](adr/0006-kafka-with-outbox.md) | Kafka + outbox + idempotent consumer | Kabul |
| [0007](adr/0007-anonymous-local-identity.md) | Anonim yerel kimlik → sonradan hesap devri | Kabul |
| [0008](adr/0008-pure-jvm-core-module.md) | Analiz çekirdeği ayrı saf JVM modülünde (`:core`) | Kabul |
