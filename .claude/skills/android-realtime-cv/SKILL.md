---
name: android-realtime-cv
description: Android gerçek zamanlı CV pipeline sözleşmeleri — CameraX + ML Kit kurulumu, backpressure, thread modeli, katman sınırları, frame bütçesi, TTS kuyruğu ve offline-first kayıt. Kamera/pose/analiz/feedback tarafında kod yazılacaksa veya bir performans/gecikme sorunu incelenecekse kullan.
---

# Android Real-Time CV Pipeline

Bu projede Android bir arayüz değil, **analizin tamamının çalıştığı yer**. Buradaki
sözleşmeler performans ve doğruluk için bağlayıcıdır.

---

## 1. Katman Mimarisi

Veri **tek yönde** akar. Her katman yalnızca bir alttakini bilir.

```
camera      CameraX: preview + ImageAnalysis
   ↓        ImageProxy
pose        ML Kit Pose Detection  →  Pose (33 landmark)
   ↓        PoseFrame(landmarks, timestamp)
features    normalization + smoothing + feature extraction     [saf Kotlin]
   ↓        FeatureFrame
engine      setup validator + rep FSM + rule engine            [saf Kotlin]
   ↓        EngineEvent (RepCompleted, FormError, SetupIssue)
feedback    öncelik + cooldown + TTS
   ↓
ui          Compose — yalnızca gözlemci
```

### Modül karşılığı (ADR 0008)

```
:app    com.android.application   →  camera · pose · feedback · ui · room
:core   kotlin("jvm")             →  features · engine        [Android plugin YOK]
```

Bağımlılık tek yönlü: `:app → :core`. `:core` hiçbir şeye bağımlı değildir.

**Bağlayıcı kural:** `features` ve `engine` katmanları **saf Kotlin**'dir — hiçbir Android
bağımlılığı içermez. `android.*`, `androidx.*`, `Context`, `Log` kullanılamaz.
Bu kural yazılı değil, **derleyici tarafından** uygulanır: `:core` modülünde Android
import'u derleme hatasıdır.

`:core` içinde loglama gerekirse `Logger` arayüzü tanımlanır, implementasyonu `:app`'ten
enjekte edilir.

Sebep: bu iki katman JVM unit testiyle, emülatör olmadan, milisaniyeler içinde test edilebilir.
`pose-math` test vektörleri burada koşar. Android bağımlılığı sızarsa bu imkan kaybolur ve
projenin doğruluk garantisi çöker.

`ui` katmanı hiçbir zaman ham landmark görmez; yalnızca `engine` çıktısını ve çizim için
hazırlanmış overlay verisini alır.

---

## 2. CameraX Konfigürasyonu

```
Preview          : ekran için
ImageAnalysis    : analiz için
  backpressureStrategy = STRATEGY_KEEP_ONLY_LATEST
  outputImageFormat    = OUTPUT_IMAGE_FORMAT_YUV_420_888
  targetResolution     = 640x480 sınıfı (yüksek çözünürlük pose doğruluğunu artırmaz)
```

**`STRATEGY_KEEP_ONLY_LATEST` zorunludur.** Frame kuyruğa alınmaz.

Gerekçe: gecikmiş analiz, yanlış zamanlı sesli uyarı demektir. Kullanıcı yukarı çıkarken
"aşağı in" duyarsa uygulamaya olan güvenini kaybeder. **Geç bilgi, yanlış bilgidir.**

- `ImageProxy.close()` her yolda çağrılır — exception durumunda bile. Kapatılmayan bir proxy
  pipeline'ı tamamen durdurur ve bu sessizce olur.
- Kamera **arka kamera** varsayılır. Ön kamera desteklenirse aynalama, feature hesabından
  ÖNCE düzeltilir (bkz. `pose-math` §1).

---

## 3. Frame Bütçesi

Hedef: **15 FPS analiz** → frame başına **66 ms**.

| Aşama | Bütçe | Not |
|---|---|---|
| ML Kit pose detection | ~30 ms | STREAM_MODE + fast model |
| Feature extraction + smoothing | < 1 ms | saf aritmetik |
| Rule engine + FSM | < 1 ms | |
| ML inference (Phase 9+) | < 5 ms | rep başına 1 kez, her frame değil |
| Overlay çizim | < 5 ms | ayrı frekansta çizilebilir |
| **Toplam** | **< 45 ms** | ~20 ms güvenlik payı |

Kurallar:
- Kamera 30 FPS üretir, analiz 15 FPS'te çalışır. **İnsan hareketinin frekans içeriği < 5 Hz**;
  Nyquist gereği 15 Hz fazlasıyla yeterlidir. 30 FPS analiz iki kat pil harcayıp sıfır doğruluk ekler.
- Frame atlama `STRATEGY_KEEP_ONLY_LATEST` ile doğal olarak gerçekleşir; manuel sayaçla
  frame atlama **yazma** — timestamp'i bozar.
- Gerçek zamanlı yola yeni bir iş eklenirken **ölçüm raporu zorunludur**: cihaz, FPS,
  frame başına ms dağılımı.

### Ölçüm

Frame işleme süresi her zaman ölçülür ve `StateFlow` ile debug ekranına verilir.
Ortalama değil **p95** izlenir — ortalama iyi görünürken p95 bütçeyi aşıyorsa
rep sayımı düzensiz frame kayıplarından bozulur.

---

## 4. Thread Modeli

```
ImageAnalysis executor  : tek thread'lik dedicated executor (main DEĞİL)
ML Kit çağrısı          : aynı analiz thread'i
features + engine       : aynı analiz thread'i (saf hesap, < 2 ms)
feedback / TTS          : ayrı scope, main-safe
Room yazma              : Dispatchers.IO
UI                      : Dispatchers.Main, yalnızca StateFlow collect
```

- Analiz zincirinin tamamı **tek thread'de sıralı** çalışır. Paralelleştirme yapılmaz:
  hesap zaten 2 ms ve sıra garantisi doğruluktan daha değerlidir. Out-of-order frame,
  FSM'i sessizce bozar.
- FSM ve filtre durumları **yalnızca analiz thread'inden** yazılır. Paylaşılan mutable
  durum yok; UI'ya `StateFlow` ile immutable snapshot verilir.
- `viewModelScope`/lifecycle: kamera `ON_STOP`'ta durur, `ON_START`'ta yeniden bağlanır.
  Duraklamada FSM durumu **korunur** ama filtre durumu **sıfırlanır** (500 ms'den uzun
  kesinti sonrası One-Euro geçmişi geçersizdir).

---

## 5. Zaman Damgası

```
dt = frame_timestamp_now - frame_timestamp_prev     // GERÇEK timestamp
```

**Sabit FPS varsayarak `dt = 1/30` yazmak yasaktır.** Frame düşünce One-Euro filtresi
ve tüm hız feature'ları bozulur; bu, cihaz ısındığında ortaya çıkan ve tekrar üretilmesi
çok zor olan bir hata sınıfıdır.

Kaynak: `ImageProxy.imageInfo.timestamp` (nanosaniye). Sistem saati (`System.currentTimeMillis`)
kullanılmaz — saat değişimi/uyku durumundan etkilenir.

---

## 6. TTS Kuyruk Yönetimi

```
QUEUE_FLUSH   : geçerliliğini yitirmiş cue kesilir, yenisi hemen konuşur
cooldown      : aynı hata 4.0 s, herhangi bir cue 2.5 s, rep başına en fazla 1
safety cue    : cooldown'ı bypass eder, kuyruğun başına geçer
```

- Bir cue söylenmeden önce **hâlâ geçerli mi** kontrol edilir. Kuyrukta beklerken kullanıcı
  hatayı düzeltmişse cue iptal edilir.
- TTS init asenkron ve başarısız olabilir → hazır değilse cue **sessizce düşürülür**,
  kuyruğa birikmez.
- Ses odağı (audio focus) istenir; kullanıcının müziği duck edilir, durdurulmaz.
- Kullanıcı feedback sıklığını ayarlayabilir (`minimal / normal / detaylı`) — cooldown
  çarpanı olarak uygulanır.

---

## 7. Offline-First Kayıt

```
Antrenman → Room (yerel, tek doğruluk kaynağı)
          → sync kuyruğu → backend (Phase 10+)
```

- Oturum **yerelde tamamlanır**. Ağ hatası kullanıcının antrenmanını asla etkilemez.
- Her oturum bir `client_session_id` (UUID) taşır → backend tarafı idempotent.
- Senkronizasyon WorkManager ile, ağ kısıtıyla, exponential backoff.
- `user_id` ilk açılışta yerel olarak üretilir (anonim). Hesap oluşturulduğunda
  bu profil devredilir — veri kaybı ve migration yoktur.

---

## 8. Gizlilik — Tartışmasız

- **Frame, bitmap veya video hiçbir koşulda diske yazılmaz, log'lanmaz, ağa gönderilmez.**
- Debug ekranı bile görüntü kaydetmez; yalnızca landmark ve sayısal değer gösterir.
- Dataset kaydı (Phase 6+) **yalnızca landmark koordinatları** içerir — açık kullanıcı onayıyla.
- Bu kuralın "geçici debug" istisnası yoktur. Geçici kod kalıcı olur.

---

## 9. Test Stratejisi

| Katman | Test türü | Nasıl |
|---|---|---|
| `features` | JVM unit test | `pose-math` test vektörleri |
| `engine` | JVM unit test | **Pose replay**: kaydedilmiş landmark dizisi → beklenen rep sayısı ve hata listesi |
| `feedback` | JVM unit test | cooldown/öncelik mantığı, sahte saat |
| `camera`/`pose` | instrumented | yalnızca smoke test — ML Kit'i test etmiyoruz |
| `ui` | Compose test | kritik akışlar |

**Pose replay testi bu projenin en değerli test aracıdır.** Gerçek bir seti bir kez kaydet,
sonra her eşik değişikliğinde regresyon olarak koştur. Manuel test ("telefonu koy, 10 şınav
çek") tekrar üretilemez ve ölçeklenmez.

---

## 10. Yasaklar

- `features`/`engine` katmanında Android bağımlılığı
- Sabit FPS varsayarak `dt` hesaplamak
- Manuel frame atlama sayacı
- Analiz zincirini paralelleştirmek
- Spec dışında, kod içinde eşik değeri değiştirmek (→ `cv-engineer`'a bildir)
- Frame/görüntü diske yazmak — debug dahil
- `ImageProxy.close()` çağrısını atlamak
