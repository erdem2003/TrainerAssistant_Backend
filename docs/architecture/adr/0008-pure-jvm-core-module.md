# ADR 0008 — Analiz Çekirdeği Ayrı Saf JVM Modülünde

**Durum:** Kabul · Phase 0 (uygulama Phase 1)

## Bağlam

`android-realtime-cv` skill'i, `features` ve `engine` katmanlarının saf Kotlin olmasını
(hiçbir Android bağımlılığı içermemesini) şart koşuyor. Gerekçe: `pose-math` test vektörlerinin
emülatörsüz, milisaniyeler içinde koşabilmesi ve Python implementasyonuyla parity testinin
mümkün olması.

Bu kural yazılı bir konvansiyon olarak bırakılabilir ya da derleyiciye zorlatılabilir.

Ayrıca proje iki klasörde duruyor: `TrainerAsistant` (dokümanlar, `.claude/`, ileride backend)
ve `TrainerAsistantMobile` (Android uygulaması).

## Karar

**Android projesi iki Gradle modülüne ayrılır:**

| Modül | Tip | İçerik |
|---|---|---|
| `:app` | `com.android.application` | CameraX, ML Kit, Compose, Room, TTS, UI |
| `:core` | `kotlin("jvm")` — **Android plugin'i yok** | pose-math, normalization, smoothing, feature extraction, setup validator, rep FSM, rule engine, egzersiz spec modelleri |

Bağımlılık yönü tek yönlüdür: `:app → :core`. `:core` hiçbir şeye bağımlı değildir.

**İki repo ayrı kalır.** `.claude/` yalnızca ana repoda bulunur ve tek doğruluk kaynağıdır;
mobil klasöre kopyalanmaz. Çalışma sırasında `/add-dir` ile iki klasör tek oturumda birleştirilir.

## Gerekçe

**1. Kural derleyiciye devredilir.**
`:core` içinde `import android.util.Log` yazmak derleme hatasıdır. Yazılı bir konvansiyon
er ya da geç ihlal edilir — özellikle hata ayıklama sırasında "geçici" olarak. Derleyici
yorulmaz ve istisna tanımaz.

**2. Test hızı.**
`:core` testleri JVM'de koşar: emülatör yok, cihaz yok, saniyeler yerine milisaniyeler.
`pose-math` test vektörleri ve pose replay testleri her değişiklikte koşturulabilir hale gelir.
Emülatör gerektiren bir test paketi pratikte koşturulmaz.

**3. Parity testi mümkün olur.**
`:core` çıktıları ile Python implementasyonunun çıktısı aynı test vektörleri üzerinde
karşılaştırılabilir (Phase 9). Android bağımlılığı olsaydı bu karşılaştırma emülatör gerektirirdi.

**4. Sınır görünür olur.**
Modül sınırı, katman sınırının fiziksel karşılığıdır. `:core`'a Android şeyi eklemek isteyen
biri önce bu ADR'yi okumak zorunda kalır.

## Sonuçlar

- Phase 1'de modül iskeleti kurulur; `:core` başlangıçta neredeyse boş olur
- `:core` Kotlin coroutines kullanabilir (saf JVM), ama `Flow` akışlarının yönetimi `:app`'te kalır
- Egzersiz spec'leri `:core`'da veri sınıfı olarak modellenir; dosyadan/asset'ten okuma `:app`'in işi
- `:core` içinde `android.util.Log` yerine basit bir arayüz (`Logger`) tanımlanır, implementasyonu
  `:app`'ten enjekte edilir
- İki repo ayrı kaldığı için mobil çalışmalarda `/add-dir` adımı zorunlu bir alışkanlık olur

## Reddedilen Alternatifler

**Tek modül, sadece paket konvansiyonu.**
Reddedildi: hiçbir şey Android bağımlılığının sızmasını engellemiyor. Bir `Log.d` sızdığı anda
tüm test stratejisi (JVM unit test + parity) çöker ve bu sessizce olur.

**Üç modül (`:app` + `:core-pose` + `:core-engine`).**
Reddedildi: sınırlar daha net olurdu ama tek kişilik geliştirmede build karmaşıklığı faydayı
aşıyor. `:core` büyür ve içindeki iki alan bağımsız değişmeye başlarsa bölünebilir —
o zaman bu ADR güncellenir.

**Android projesini ana repoya taşımak (monorepo).**
Reddedildi: iki ayrı git repo, bitirme teslimi ve mobil/backend'in bağımsız
versiyonlanması için tercih edildi. `/add-dir` maliyeti düşük ve `.claude/` tek yerde kalıyor.

**Mobil klasöre `.claude/` kopyalamak.**
Reddedildi: `pose-math` skill'inin varlık sebebi implementasyonların ayrışmasını önlemek.
Skill'in kendisinin çatallanması tam olarak aynı hatayı yapardı — ve fark edilmesi daha zor olurdu.
