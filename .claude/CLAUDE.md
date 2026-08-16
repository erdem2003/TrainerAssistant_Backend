# AI Fitness Coach — Proje Kuralları

Android üzerinde kamera ile egzersiz analizi yapan, tekrar sayan, form hatası tespit eden ve
gerçek zamanlı sesli koçluk veren bir sistem. İlk egzersizler: push-up, squat.

Bu dosya projenin **değişmez kurallarını** tutar. Detaylı gerekçeler ADR'lerde
(`docs/architecture/adr/`), teknik sözleşmeler skill'lerde (`.claude/skills/`).

---

## 1. Kilitlenmiş Mimari Kararlar

Bu kararlar tartışılmış ve onaylanmıştır. Değiştirmek için yeni bir ADR gerekir.

| # | Karar | ADR |
|---|---|---|
| 1 | Önce rule-based, veri biriktikçe ML eklenir | 0001 |
| 2 | Tüm gerçek zamanlı analiz on-device; görüntü/video cihazdan asla çıkmaz | 0002 |
| 3 | ML analiz birimi frame değil **rep**; LSTM/Transformer kullanılmaz | 0003 |
| 4 | Normalization: hip-centered origin + torso-length scaling | 0004 |
| 5 | Backend: api-gateway + auth + user + workout + analytics (5 servis, database-per-service) | 0005 |
| 6 | Event broker Kafka + outbox pattern + idempotent consumer | 0006 |

## 1.5. Repo Konumları

Proje iki ayrı klasörde duruyor:

| Klasör | İçerik |
|---|---|
| `C:\Users\user\Desktop\TrainerAsistant` | **Ana repo:** `.claude/` (agent + skill), `docs/`, ileride `services/`, `ml/` |
| `C:\Users\user\Desktop\TrainerAsistantMobile` | **Android uygulaması** — package `com.bitirmeprojesi.trainerasistantmobile` |

`.claude/` yalnızca ana repoda bulunur ve **tek doğruluk kaynağıdır.** Mobil klasöre
kopyalanmaz — `pose-math` skill'inin varlık sebebi implementasyonların ayrışmasını
önlemek; skill'in kendisinin çatallanması aynı hatayı yapar.

Mobil kod üzerinde çalışırken oturuma mobil klasör eklenir:
```
/add-dir C:\Users\user\Desktop\TrainerAsistantMobile
```

## 2. Tartışılmaz Teknik Kurallar

- **ML Kit `z` değeri kullanılmaz.** Metrik derinlik değildir. Sadece dataset'e loglanır.
- **`inFrameLikelihood < 0.5` olan landmark'a dayanan feature `null` döner.** Tahmin edilmez,
  varsayılan değer atanmaz. Yanlış ölçmektense ölçmemek doğrudur.
- **Rep sayma asla ML değildir.** Deterministik state machine + histerezis.
- **Kamera açısı bir ürün kısıtıdır, ML problemi değildir.** Her egzersiz `required_view`
  tanımlar; Setup Validator kurulum uygun olmadan rep saymayı reddeder.
- **Eşikler mutlak değil, kişisel kalibrasyona göreli tanımlanır.**
- **Feature extraction matematiği Kotlin ve Python'da birebir aynı sonucu vermelidir.**
  Tek doğruluk kaynağı: `.claude/skills/pose-math/`. Değişiklik iki tarafta birden yapılır.
- **Yeni egzersiz eklemek kod yazmak değil, spec yazmaktır.** Motor genel kalır.

## 3. Çalışma Modu

- Yeni bir modül/katman/servis kurulmadan önce **öneri sunulur, onay beklenir.**
- Büyük refactor, dosya silme, dependency değiştirme, altyapı kurma → **önce sor.**
- Alternatifler ve trade-off'lar sunulur; tek seçenek dayatılmaz.
- Her fazın bir **çıkış kriteri** vardır (`docs/roadmap.md`); kriter sağlanmadan sonraki faza geçilmez.

## 4. Faz Durumu

Güncel faz: **Phase 10 — Microservices** (backend kuruluyor)

Tamamlananlar: Phase 0-3 (mobil, sayım çalışıyor), Phase 5 (sesli koçluk),
Phase 6-8 (veri seti + ML model), Phase 9 (hibrit form analizi).
Phase 4 (squat) bilinçli olarak atlandı — tek egzersizde derinlik tercih edildi.

Veri sözleşmeleri donduruldu: `workout` (ADIM 19), `user` + `analytics` (ADIM 20).

Faz tablosunun tamamı: `docs/roadmap.md`

## 5. Şu Anda YAPILMAYACAKLAR

Aşağıdakiler ilgili fazları gelene kadar oluşturulmaz. Erken kurmak, doldurulmayan
iskelet ve bakımsız kod üretir.

- `android/`, `services/`, `infrastructure/`, `ml/`, `data/` klasörleri
- Herhangi bir dependency, build dosyası, Docker/Kubernetes tanımı
- Recommendation, Notification, Exercise servisleri (ayrı servis olarak kurulmayacak — bkz. ADR 0005)
- TensorFlow Lite, ONNX runtime, LSTM/Transformer
- ELK/Loki, service mesh, APM

## 6. Agent Sorumlulukları

| Agent | Alan | Ne zaman |
|---|---|---|
| `architect` | Sistem sınırları, ADR, cross-cutting kararlar, arbitraj | Aktif |
| `cv-engineer` | Pose matematiği, feature, FSM, eşik, form kuralları | Aktif |
| `android-engineer` | Kotlin/Compose/CameraX/ML Kit/Room/TTS | Aktif |
| `ml-engineer` | Dataset, training, export, parity | Phase 7'de eklenecek |
| `backend-engineer` | FastAPI, Postgres, Kafka, Redis, güvenlik | Aktif |
| `devops-engineer` | Docker, Kubernetes, CI/CD | Phase 13'te eklenecek |

**Kural:** Bir agent kendi alanı dışında karar vermez. İki alanı birden etkileyen bir değişiklik
(ör. feature şemasının değişmesi) `architect` koordinasyonunda kararlaştırılır.

## 7. Dil

- Kod, tanımlayıcılar, commit mesajları, teknik terimler: **İngilizce**
- Dokümantasyon ve tartışma: **Türkçe**
- Kullanıcıya gösterilen/söylenen metinler: TR birincil, EN ikincil (i18n baştan planlanır)
