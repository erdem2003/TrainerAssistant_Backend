# Development Roadmap

Her fazın **tek başına gösterilebilir bir çıktısı** vardır. Ara teslim ne zaman olursa olsun,
o ana kadar tamamlanmış fazlar sunulabilir bir bütün oluşturur.

**Çıkış kriteri sağlanmadan sonraki faza geçilmez.** Kriter sübjektif değil, ölçülebilir olmalıdır.

---

## Genel Sıra

```
0 ── 1 ── 2 ── 2.5 ── 3 ── 4 ── 5 ──┬── 6 ── 7 ── 8 ── 9
                                     │
                                     └── 10 ── 11 ── 12 ── 13
```

Phase 5'ten sonra iki kol paralel ilerleyebilir: **veri/ML kolu** (6-9) ve
**backend kolu** (10-13). Tek kişilik geliştirmede sırayla, ama bağımlılıkları yok.

---

## Phase 0 — Mimari & CV Kararları ✅

Karar dokümanları, agent ve skill tanımları.

- **Çıktı:** `.claude/` (3 agent + 3 skill) · `docs/` (overview + 7 ADR + 3 CV spec + roadmap)
- **Çıkış kriteri:** Tüm ADR'lerin "Reddedilen Alternatifler" bölümü dolu; her formülün
  en az bir test vektörü var; push-up ve squat spec'leri aynı şablona birebir uyuyor
- **Gösterilebilir:** Mimari kararlar sunumu — bitirme savunmasının iskeleti

## Phase 1 — Android İskelet

CameraX + ML Kit + skeleton overlay.

- **Çıktı:** Kamerayı açan, pose tespit eden, iskelet çizen uygulama
  + `:app` / `:core` modül ayrımının kurulması (ADR 0008)
- **Çıkış kriteri:** Orta seviye bir cihazda **15 FPS'te stabil**, p95 frame süresi < 45 ms,
  5 dakika kesintisiz çalışmada bellek sızıntısı yok; `:core` modülü Android bağımlılığı
  olmadan derleniyor
- **Gösterilebilir:** Çalışan iskelet takibi — görsel olarak etkileyici, ilk demo için ideal

## Phase 2 — Feature Extraction & Setup Validator

Normalization, One-Euro smoothing, feature hesabı, kamera kurulum doğrulama.

- **Çıktı:** `features` katmanı (`:core` modülünde) + Setup Validator + debug ekranı
- **Çıkış kriteri:**
  1. `pose-math` primitif test vektörlerinin **tamamı** geçiyor
  2. `feature-spec.md`'deki **her türetilmiş feature için test vektörü yazıldı** ve geçiyor —
     özellikle `hip_vertical_offset` ve `hip_above_knee`'nin **işaret konvansiyonu** gerçek
     kayıtla doğrulandı
  3. Setup Validator yanlış kurulumu (ön görüş, çok uzak, sallanan telefon) doğru reddediyor

> İşaret doğrulaması gözden kaçarsa tüm derinlik ve hizalama kuralları sessizce ters çalışır
> ve kod doğru görünür. Bu fazın en kritik kontrolü budur.
- **Gösterilebilir:** Canlı feature değerleri + kurulum koçu ("telefonu yan tarafına koy")

## Phase 2.5 — Kalibrasyon

Kişisel ROM ölçümü ve eşiklerin kalibrasyona bağlanması.

- **Çıktı:** 3 tekrarlık kalibrasyon akışı, kişisel referansların yerel kaydı
- **Çıkış kriteri:** Farklı boy/esneklikteki **en az 3 kişide** kalibrasyon anlamlı ve
  tekrarlanabilir sonuç veriyor (aynı kişi iki kez kalibre edildiğinde fark < %10)
- **Gösterilebilir:** Aynı eşiğin farklı kişilerde farklı mutlak değerlere karşılık gelmesi —
  cross-user genelleme probleminin çözümü olarak anlatılabilir

> Bu faz ML'den önce gelmek zorunda: tüm eşikler buna dayanıyor.

## Phase 3 — Push-Up Rule-Based Prototip

Rep FSM + rule engine + push-up spec'in uygulanması.

- **Çıktı:** Şınav sayan ve form hatası tespit eden çalışan sistem
- **Çıkış kriteri:** En az 3 kişide, kişi başına 3 set: **rep sayımı ≥ %98 doğru**;
  pose replay test seti oluşturulmuş ve regresyon olarak koşuyor
- **Gösterilebilir:** Gerçek şınav sayımı + ekranda hata tespiti

## Phase 4 — Squat Rule-Based Prototip

Aynı motor, yeni spec.

- **Çıktı:** Squat desteği
- **Çıkış kriteri:** Rep sayımı ≥ %98; **motor kodunda değişiklik yapılmadı** (yalnızca spec eklendi)
- **Gösterilebilir:** İki egzersiz, tek motor — mimarinin doğruluğunun kanıtı.
  "Yeni egzersiz eklemek kod değil, spec yazmak" iddiasının ispatı

## Phase 5 — Gerçek Zamanlı Feedback & TTS

Feedback engine + sesli koçluk + eller serbest mod.

- **Çıktı:** **İlk kullanılabilir ürün.** Konuşan, koçluk yapan uygulama
- **Çıkış kriteri:** 3 kişilik kullanım testinde "rahatsız edici" geri bildirimi yok;
  cue gecikmesi < 300 ms; cooldown mantığı doğru çalışıyor
- **Gösterilebilir:** Uçtan uca demo — telefonu koy, spor yap, koçluk al

> **Neden veri toplamadan önce:** kullanıcılar ancak faydalı bir uygulamayı düzenli kullanır;
> düzenli kullanım olmadan farklı evlerden/salonlardan veri gelmez.

---

## Veri / ML Kolu

## Phase 6 — Data Collection Pipeline

- **Çıktı:** Kayıt modu (açık onayla), Parquet şeması, yerel + yükleme akışı
- **Çıkış kriteri:** Gerçek kullanımdan veri akıyor; şema `dataset-labeling` skill'iyle uyumlu;
  kayıtta hiçbir görüntü verisi yok (denetlendi)
- **Gösterilebilir:** Toplanan veri istatistikleri

## Phase 7 — Dataset & Labeling

- **Çıktı:** Etiketleme aracı (rule ön-etiket → insan doğrulama), etiketli dataset
- **Çıkış kriteri:** **≥ 15 kullanıcı · kullanıcı başına ≥ 40 rep · her hata sınıfı için
  ≥ 150 pozitif örnek.** Bu bir tarih değil, bir eşiktir — sağlanmadan Phase 8 başlamaz
- **Gösterilebilir:** Dataset istatistikleri, sınıf dağılımı, kullanıcı çeşitliliği

## Phase 8 — Baseline ML Model

- **Çıktı:** Logistic Regression (sanity) → LightGBM multi-label, rep-level
- **Çıkış kriteri:** **User-based split'te (GroupKFold)** rule engine'i en az bir hata
  sınıfında anlamlı şekilde yeniyor. Yenmiyorsa model **eklenmez** — bu geçerli bir sonuçtur
  ve bitirme raporunda böyle yazılır
- **Gösterilebilir:** Model karşılaştırma tablosu, per-label PR-AUC, feature importance

## Phase 9 — Hybrid Form Analysis

- **Çıktı:** On-device inference + rule/ML katman entegrasyonu
- **Çıkış kriteri:** Kotlin ve Python feature extraction **parity testleri geçiyor**;
  inference < 5 ms; rep sonu verdict akışı çalışıyor
- **Gösterilebilir:** Rule ve ML çıktılarının yan yana karşılaştırması

---

## Backend Kolu

## Phase 10 — Microservices

- **Çıktı:** `api-gateway` + `auth` + `user` + `workout` + `analytics`, Postgres, Redis,
  Docker Compose
- **Çıkış kriteri:** Uçtan uca senkron çalışıyor; anonim profil hesaba devrediliyor (claim);
  idempotent sync doğrulandı (aynı oturum iki kez → tek kayıt); hiçbir servis başka
  servisin DB'sine dokunmuyor
- **Gösterilebilir:** Servis diyagramı + çalışan API + antrenman geçmişi

> `backend-engineer` agent'ı bu fazın başında oluşturulur.

## Phase 11 — Event-Driven

- **Çıktı:** Kafka (Redpanda), outbox relay, idempotent consumer
- **Çıkış kriteri:** `WorkoutCompleted` → analytics akışı çalışıyor; **event replay ile
  analytics sıfırdan yeniden hesaplanabiliyor**; tekrarlanan event ikinci kez işlenmiyor
- **Gösterilebilir:** Event akışı + replay demosu — dağıtık sistem yetkinliğinin en güçlü kanıtı

## Phase 12 — Observability

- **Çıktı:** OpenTelemetry tracing, Prometheus metrikleri, Grafana dashboard'ları
- **Çıkış kriteri:** Bir mobil isteğin **uçtan uca trace'i** görünüyor — Kafka sınırında
  kopmadan; RED metrikleri ve consumer lag dashboard'da
- **Gösterilebilir:** Canlı trace ve dashboard

## Phase 13 — Deployment

- **Çıktı:** Kubernetes manifest'leri, CI/CD
- **Çıkış kriteri:** Tek komutla ayağa kalkıyor; parity testleri CI'da koşuyor
- **Gösterilebilir:** Çalışan cluster + otomatik pipeline

---

## Ara Teslim Planı

Ara teslim tarihi henüz belirtilmedi. Tarih netleştiğinde bu bölüm doldurulacak.

Hangi fazlara kadar gelinebildiğine göre gösterilebilir paketler:

| Fazlar tamam | Sunulabilecek hikâye |
|---|---|
| 0-1 | Mimari kararlar + çalışan pose tracking |
| 0-2.5 | + Kamera kurulum koçu + kişisel kalibrasyon (cross-user problemi ve çözümü) |
| 0-4 | + İki egzersizde rep sayma ve form tespiti (tek motor, iki spec) |
| 0-5 | **+ Sesli koçluk — tam çalışan bir ürün.** En güçlü ara teslim noktası |
| 0-9 | + ML katmanı ve deneysel sonuçlar (akademik ağırlık burada) |
| 0-13 | Tam sistem |

**Öneri:** Ara teslim için hedef **Phase 5**. O noktada elde çalışan, gösterilebilir ve
kendi başına anlamlı bir ürün var. Phase 3-4'te durursan sayı sayan bir uygulama,
Phase 5'te durursan bir koç göstermiş olursun.

---

## Faz Değiştirme Kuralı

Bir fazın sırası değişecek veya atlanacaksa **kullanıcıya sorulur.** Fazlar arası
bağımlılıklar gerçek:

- 2.5 (kalibrasyon) → 3, 4 (eşikler buna dayanıyor)
- 3, 4 (rule engine) → 7 (etiketleme rule ön-etiketine dayanıyor)
- 6, 7 (veri) → 8 (eşik sağlanmadan model yok)
- 10 (servisler) → 11 (servis yokken event yok)
