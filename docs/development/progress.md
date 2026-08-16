# Geliştirme Takibi — Android

> Çalışma şekli: **tek adım → planla → uygula → dur → doğrula → commit → onay bekle.**
> Kullanıcı "devam" / "başlayalım" demeden sonraki adıma geçilmez.

**Numaralandırma:** Makro **Phase**'ler (`docs/roadmap.md`, ADR'ler) stratejik fazlardır.
Buradaki **ADIM**'lar onların içindeki uygulama birimleridir. İkisi karıştırılmamalı.

---

## Durum

```
Current Step      : ML veri seti + sınıflandırıcı (ADIM 16.5 — plan dışı ara adım)
Status            : ✅ TAMAMLANDI — model eğitildi, Desktop/trainer_ann/
Next Step         : ADIM 17 — modeli :core'a bağla + kural motoruyla karşılaştır
Last Completed    : 173 video → features.csv → MLP (835 param), test %100
Known Issues      : ADIM 10-13 commit'lenmedi (kullanıcı isteğiyle bekletiliyor)
                    ⚠️ Frame bütçesi temiz ölçüm bekliyor (yukarı bak)
                    ⚠️ Test %100 ama weak supervision tavanı var — bkz. aşağı
                    ⚠️ Eğitim MediaPipe landmark'ıyla, cihaz ML Kit — alan farkı
                    ölçülmedi
                    ❌ torso_inclination "riski kapandı" notu YANLIŞTI — iki ayrı
                    hata çıktı, aşağıda
```

### 🔴→✅ İki gerçek hata: `torso_inclination` (2026-08-15)

Yukarıdaki "torso_inclination riski kapandı" notu yanlış çıktı. Cihaz ölçümü
kullanıcının **sağa dönük** durduğu tek bir kurulumdan alınmıştı; iki hata da o
kurulumda görünmez.

**Hata 1 — `angleToHorizontal` sola dönük vücutta ~180 dönüyordu.**
`|atan2(dy, dx)|` yukarı/aşağı ayrımını siler, sağ/sol ayrımını silmez:

| Gövde | P → Q | Eski | Yeni |
|---|---|---|---|
| sağa uzanan | omuz(400,200) → ayak(50,210) | 1.6° | 1.6° |
| sola uzanan | omuz(50,200) → ayak(400,210) | **178.4°** | 1.6° |

Sonuç: kullanıcı ters yöne dönünce `maxTorsoInclination = 35` kapısına takılıyor ve
**Setup Validator şınavı hiç başlatmıyordu.** Kullanıcının bildirdiği "incl bende
yüksek çıkıyor" bu.

Gözden kaçma sebebi: spec vektörleri (V1–V4, H1–H3) ve birim testler yalnızca
`dx >= 0` tarafını kapsıyordu.

**Hata 2 — `midNormalized` iki ayak bileğini birden şart koşuyordu.**
Yan görüşte uzak ayak kapalı → `null` → tüm feature vektörü düşüyor. Aynı kural
`isFullBodyVisible`'da doğru yazılmıştı ("her eklem için en az bir taraf yeterli");
`midNormalized` ona uymuyordu.

**Etkisi (offline veri setinde):**

| | Önce | Sonra |
|---|---|---|
| Kabul edilen kayıt | 78 / 173 | 144 / 173 |
| `TOP` kare | **0** | 2596 |
| `BOTTOM` kare | **0** | 2153 |

Düzeltmeden önce veri setinde tek bir şınav örneği bile yoktu.

Değişenler: `PoseMath.kt` (`fold` eklendi), `PushUpFeatures.kt` (`midNormalized`),
`pose-math/SKILL.md`, `pose-math/references/test-vectors.md` (H4–H6, V5),
`PoseMathTest` + `PushUpFeaturesTest` (+7 test). Tüm `:core` testleri geçiyor.

**Ders:** cihaz doğrulaması tek bir kurulumdan yapılırsa simetri hatalarını
göstermez. Sonraki cihaz testleri **iki yöne de dönerek** yapılmalı.

### ML veri seti ve sınıflandırıcı — özet

Ayrıntı: `C:\Users\user\Desktop\trainer_ann\OZET.md`

- 173 video → MediaPipe BlazePose (PC, 9.9 dk) → `.poserec`
- `.poserec` → **Kotlin `:core`** (`DatasetToolTest`) → `features.csv`, 7135 satır.
  Feature matematiği Python'a kopyalanmadı; parity kuralı korundu.
- MLP 7→32→16→3, 835 parametre. Bölme **kayda göre** (101/22/21 kayıt).
- Test doğruluğu %100 — ama etiketler kural motorundan geldiği için bu tavan
  beklenen sonuç, saha kanıtı değil.
- Bağımsız ölçümler: en iyi global eşik görülmemiş kayıtlarda %79.9 (eğitimde
  %95.1) → eşik kişiden kişiye taşınmıyor. Tekrar sayımı 20/21 klip doğru.
- `knee_angle`'ın permutation importance'ı 0.000 — şu an bilgi taşımıyor.

**Bağımlılık engeli kalktı:** 835 parametre için TFLite/ONNX gerekmiyor; ağırlıklar
`:core`'un bağımlılıksız okuyabileceği düz metin biçiminde de yazıldı
(`model/pose_classifier.txt`).

**Neden PC'de:** Android 14 FUSE katmanı, `adb push` ile harici depolamaya yazılan
dosyaları uygulamadan gizliyor (uygulamadaki "Bulunan video: 0" bu). Dahili
depolamaya kopyalama da bellek hatasıyla çöktü.

### 🔴 Açık: `camera_drift` gerçek tekrarlarda tetiklenecek (ADIM 16'da fark edildi)

`camera_drift` = `mid_hip`'in image-normalized hızı. Ama **şınav yaparken kalça
gerçekten hareket ediyor** — telefon değil, kullanıcı. Kaba hesap:

```
kalça iniş yolu   ≈ 0.12 image-norm birim
tam tekrar süresi ≈ 2 sn, gidiş-dönüş 0.24 birim
ortalama hız      ≈ 0.12 birim/sn      eşik: 0.05
```

Yani sayım başlar başlamaz `CAMERA_STABLE` düşer, `setup` READY olmaktan çıkar ve
`WorkoutSession` FSM'e `null` besler → **sayım durur.**

Cihaz testinde görülmedi çünkü statik plank pozları ölçüldü, gerçek tekrar yapılmadı.

**✅ ÇÖZÜLDÜ (A seçeneği).** `SetupValidator.validate(..., enforceStability)` eklendi;
`WorkoutSession` sayım fazında `false` geçiyor. `cameraDrift` değeri **raporlanmaya
devam ediyor** — yalnızca kapı kapanıyor, ölçüm kaybolmuyor.

Telefonun sonradan devrilmesi bu kontrol olmadan da yakalanıyor: `IN_POSITION` ve
`CORRECT_ANGLE` sayım fazında devrede kalıyor.

Regresyon testi: `sayim sirasinda vucut hareket etse de tekrarlar sayilir`.

---

### ⚠️ Bulgu: sayaç kilitlenmeden SONRA artıyor (ADIM 16)

Dirsek açısı **180° civarında landmark konumuna aşırı duyarlı**: 0.001 birimlik konum
hatası ≈ 1°, oysa 70° civarında aynı hata ≈ 0.35°. One-Euro filtresinin hareket
sırasındaki gecikmesi bu bölgede büyük açı hatasına dönüşüyor.

Sonuç: `p` kilitlenme değerine ancak hareket durduktan **birkaç kare sonra** ulaşıyor,
yani tekrar kullanıcı tepede durduktan sonra sayılıyor. Sentetik testte bu gecikme
~8 kare (≈530 ms) çıktı, ama orada hız sabit; gerçek harekette kullanıcı tepeye
yaklaşırken yavaşladığı için daha az olmalı.

**Aksiyon:** cihazda ölçülecek. Gecikme belirginse `PARTIAL_LOCKOUT` eşiği (ADIM 17)
üst uçta alt uçtakinden geniş toleransla konmalı, ve sesli geri bildirim (ADIM 19)
tasarlanırken sayaç gecikmesi hesaba katılmalı.

---

### ⚠️ Spec'te tespit edilen tutarsızlıklar (ADIM 12'de bulundu)

Üçü de `feature-spec.md` / `pose-math` güncellemesi gerektiriyor. İmplementasyon
aşağıdaki yorumlarla yapıldı, dokümanlara **henüz dokunulmadı**.

| # | Sorun | Alınan karar |
|---|---|---|
| 1 | `hip_vertical_offset` formülü sonunda `/ torso_length` var, ama dosya başlığı "tüm hesaplar normalize koordinatta" diyor → çift ölçekleme | İkinci bölme uygulanmadı. İki okumanın matematiksel olarak aynı sonucu verdiği doğrulandı |
| 2 | ~~`\|KNEE.x − SHOULDER.x\| < 0.1` kapısının birimi belirsiz~~ **ÇÖZÜLDÜ** | Cihaz ölçümü karar verdi: torso birimi doğru ama **değer 0.5 olmalı**. 0.1 ile dimdik duran kişiye `hipOff -0.52 PIKE` deniyordu. Spec'in 0.1'i image-height okumasına göre yazılmış (torso 0.18 iken ≈ 0.55 torso). Regresyon testi eklendi |
| 3 | **`hip_velocity_y` tanımı olduğu gibi çalışmaz.** Normalize koordinatın merkezi `mid_hip`, yani kalça tanım gereği hep (0,0) → hızı her zaman sıfır | Hız feature'ları image-normalized koordinattan türetilip torso'ya bölünüyor (birim: torso/s). Squat'ta ADIM 21'de aynı duvara çarpılacak |

### Frame bütçesi ölçümleri

| Aşama | Ortam | FPS | p95 | Not |
|---|---|---|---|---|
| ADIM 4 (analyzer boş) | Aydınlık | 29.8 | ~0 ms | Referans |
| ADIM 4 (analyzer boş) | Loş | 14.3 | ~0 ms | Sensör pozlaması |
| ADIM 5 (ML Kit) | Aydınlık | 27.5 | 33 ms | ML Kit maliyeti |
| **ADIM 6 (+ iskelet çizimi)** | Aydınlık | **20.0** | **40 ms** | ⚠️ izlenecek |
| ADIM 13 (tam zincir) | Önden, **ekran kaydı açık** | 14.3-14.4 | 67-132 ms | drop 0-43/60 |
| ADIM 13 (tam zincir) | Yandan, **ekran kaydı açık** | 18.6-21.0 | 60-115 ms | drop 24-35/60 |

**⚠️ 2026-08-14 ölçümü KİRLİ — henüz sonuç çıkarılmamalı.** Tüm bu sayılar ekran kaydı
çalışırken alındı; kaydedici gerçek zamanlı video encode edip aynı CPU'yu kullanıyor.
Ayrıca `drop` seans boyunca 24 → 43 diye tırmandı, bu termal kısıtlama işareti.

**Yapılacak:** ekran kaydı kapalı, 1 dakika çalıştırıp tek ekran görüntüsü ile temiz
ölçüm. Referans: ADIM 6'da 20 FPS / 40 ms idi. Temiz sayı da 66 ms'yi aşıyorsa
optimizasyon adımı ADIM 15'ten önce araya girer.

**Risk notu:** düşen frame oranı yüksek kalırsa ADIM 15'teki rep FSM etkilenebilir.
Tasarım gerçek timestamp + histerezis kullandığı için dayanıklı olmalı, ama orada
ayrıca doğrulanacak.

**Yorum:** ML Kit frame başına ~33 ms (p95) alıyor. 27.5 FPS'te frame aralığı 36 ms,
yani analiz aralığın **%90'ını** kullanıyor. Bütçe (66 ms) aşılmadı ama pay dar.

**ADIM 6 sonrası:** İskelet çizimi eklenince FPS 27.5 → 20, p95 33 → 40 ms. Çizim GPU'da
yapılıyor ama p95 yine de arttı — muhtemel sebepler: termal kısıtlama veya Compose'un
yeniden çiziminin CPU'da analizle yarışması.

Hâlâ bütçe içinde (66 ms) ve hedefin (15 FPS) üstünde, ama trend yukarı. **İzlenecek.**

**Fırsat:** Analiz 20 FPS'te koşuyor, oysa ihtiyacımız **15 FPS**. Frame'lerin bir kısmını
bilinçli atlayarak pil ve ısınmayı azaltabiliriz. Optimizasyon adımı olarak not edildi —
rep sayacı çalışır hale gelip gerçek bir sette ölçüm alındıktan sonra karar verilecek.
Şimdi optimize etmek erken: hangi işin pahalı olduğunu henüz bilmiyoruz.

### ⚠️ Bulgu: kamera FPS'i ışığa bağlı

Loş ortamda kamera pozlama süresini uzatıp **kendiliğinden 14 FPS'e düşüyor** — bu bizim
kodumuzun yavaşlığı değil, sensör davranışı (p50/p95 sıfırken ölçüldü).

**Proje açısından sonucu:** "kamera 30 FPS verir, biz 15'te analiz ederiz" varsayımı her
ortamda geçerli değil. Loş bir spor salonunda frame atma lüksü kalmıyor, her frame işlenmek
zorunda. 14 FPS'te frame başına 71 ms bütçe var; ML Kit ~30 ms ile hâlâ sığıyor ama pay daralıyor.

**Aksiyon:** Setup Validator'a (ADIM 13) **ışık yeterliliği kontrolü** eklenmeli —
ölçülen FPS eşiğin altındaysa kullanıcıya "ortamı aydınlat" uyarısı. Bu, `docs/computer-vision/`
altındaki setup check listesine eklenecek yeni bir madde.

**ADIM 3'te alınan karar:** `PreviewView.ScaleType.FIT_CENTER` (varsayılan `FILL_CENTER` değil).
Sebep: (1) kullanıcı kurulumda tüm vücudunun kadrajda olduğunu görmeli, (2) ADIM 6'da iskelet
overlay'inin koordinat eşlemesi kırpılmamış görüntüde basit ölçekleme + kaydırmaya iniyor.

**Ertelenen kararlar:**
- Java 11 → 17 yükseltmesi: şimdilik 11'de kalındı. CameraX ve ML Kit 11 ile çalışıyor.
  Bir kütüphane 17 isterse o adımda yapılır.
- **AGP 8.10 / compileSdk 35 sabitlendi.** AndroidX sürümleri Compose BOM 2024.09.00 ile
  aynı döneme hizalandı (ADIM 1'de zorunlu düzeltme — aşağıya bak). Yükseltme gerekirse
  BOM + AndroidX + AGP + compileSdk **birlikte** ele alınmalı, tek tek değil.

**ADIM 1'de çözülen sorun:** Android Studio şablonu tutarsız sürüm seti üretmişti
(Compose BOM Eylül 2024 + core-ktx 1.19.0 / lifecycle 2.11.0 gibi çok yeni AndroidX).
Bu kütüphaneler compileSdk 37 ve AGP 9.1 istiyordu → 11 adet AAR metadata hatası.
Çözüm: `coreKtx 1.15.0`, `lifecycleRuntimeKtx 2.8.7`, `activityCompose 1.9.3`.
Bizim `:core` değişikliğimizle ilgisi yoktu, ilk `:app` derlemesinde ortaya çıktı.

---

## ADIM Listesi

Makro faz eşlemesi: ADIM 1-6 → Phase 1 · 7-12 → Phase 2 · 13-14 → Phase 2.5 ·
15-17 → Phase 3 · 18-19 → Phase 5 · 20 → Phase 5 · 21 → Phase 4

| # | Adım | Yeni dependency | Beklenen çıktı | Doğrulama | Zorluk | Durum |
|---|---|---|---|---|---|---|
| 1 | Proje doğrulama + `:core` modülü | kotlin-jvm plugin | `:app → :core` bağı, JVM testi koşuyor | `gradlew :core:test` yeşil, app açılıyor | Düşük | ✅ |
| 2 | Kamera izni | — | İzin isteme + red durumu ekranı | İzin diyaloğu çıkıyor, red edilince açıklama | Düşük | ✅ |
| 3 | CameraX Preview | camerax (4 modül) | Ekranda canlı kamera | Görüntü geliyor, rotasyon doğru | Orta | ✅ |
| 4 | ImageAnalysis + FPS ölçümü | — | Boş analyzer + canlı FPS/p95 göstergesi | ~30 FPS, ANR yok, `ImageProxy` sızmıyor | Orta | ✅ |
| 5 | ML Kit Pose Detection | mlkit pose-detection | Frame başına 33 landmark + inference ms | Log'da 33 landmark, inference < 40 ms | Orta | ✅ |
| 6 | Skeleton overlay | — | İskelet çizimi | İskelet vücutla hizalı (koordinat dönüşümü doğru) | Orta-Yüksek | ✅ |
| 7 | `PoseFrame` + ML Kit adapter | — | `:core`'da ML Kit'ten bağımsız model | `:core` ML Kit import etmiyor, overlay `PoseFrame`'den çiziyor | Düşük-Orta | ✅ |
| 8 | Açı hesabı (`:core`) | — | `angleAt`, eksene göre açı | Test vektörleri A1-A6, V1-V4, H1-H3 | Düşük | ✅ |
| 9 | Confidence gating + taraf seçimi | — | `null` politikası, histerezisli taraf seçimi | Vektörler C1-C4, S1-S5 | Düşük | ✅ |
| 10 | Normalization | — | hip-centered + torso-scaled | Vektörler N1-N6 + ölçek değişmezliği | Orta | ✅ |
| 11 | One-Euro filter | — | Adaptif smoothing | Vektörler E1-E5 (özellikle E5: değişken `dt`) | Orta | ✅ |
| 12 | Push-up feature extraction | — | `elbow_angle`, `hip_vertical_offset`, `torso_inclination`, hızlar | **Türetilmiş feature test vektörleri** + canlı debug ekranı | Orta | ✅ |
| 13 | Setup Validator | — | Kamera kurulum koçu | Ön görüş / uzak / sallanan telefon reddediliyor | Orta | ✅ |
| 14 | Kalibrasyon akışı | — | 3 tekrarlık kişisel ROM ölçümü | 2 kişide tekrarlanabilir sonuç (fark < %10) | Orta-Yüksek | ✅ |
| 15 | Faz sinyali + Rep FSM | — | Histerezisli state machine | Sentetik sinyalle unit test, çift sayım yok | Orta-Yüksek | ✅ |
| 16 | Rep counter UI + pose replay altyapısı | — | Ekranda sayaç + kayıtlı sekans testi | Gerçek sette rep sayımı ≥ %98 | Orta | ⏳ |
| 17 | Push-up form kuralları | — | Hata tespiti (`pushup.md` spec'i) | Kasıtlı hatalı tekrarlar doğru tespit ediliyor | Orta | — |
| 18 | Feedback Engine | — | Öncelik + cooldown mantığı | Unit test (sahte saat), rep başına ≤ 1 cue | Orta | — |
| 19 | TextToSpeech | — | Sesli koçluk | Cue gecikmesi < 300 ms, ses odağı doğru | Düşük-Orta | — |
| 20 | Workout session + Room | room | Yerel antrenman kaydı | Uygulama kapanıp açılınca geçmiş duruyor | Orta | — |
| 21 | **Squat** (spec ekleme) | — | İkinci egzersiz | **Motor kodu değişmedi** — sadece spec eklendi | Orta | — |

Durum: `⏳` planlandı · `🔨` devam ediyor · `✅` tamam · `—` başlanmadı

> **ADIM 21 kritik test:** squat eklerken `:core`'daki motor kodu değişmek zorunda kalırsa
> mimari iddiamız ("yeni egzersiz = yeni spec") yanlışlanmış olur. O noktada spec formatı
> düzeltilir, motora egzersize özel kod eklenmez.

---

## Adım Bitirme Kuralı

Bir adım şunlar sağlanmadan `✅` işaretlenmez:

1. Doğrulama adımı kullanıcı tarafından çalıştırıldı ve sonucu bildirildi
2. Varsa test vektörleri yeşil
3. Commit mesajı önerildi
4. Bu dosyadaki durum güncellendi

---

## Değişiklik Günlüğü

| Tarih | Adım | Not |
|---|---|---|
| 2026-08-13 | Phase 0 | 22 doküman, 8 ADR tamamlandı |
| 2026-08-13 | ADIM 1 | ✅ `:core` modülü kuruldu, JVM testi geçti, uygulama açıldı. AndroidX sürüm hizalaması yapıldı. |
| 2026-08-13 | ADIM 1+ | `.gitignore` düzeltildi (`/build` → `build/`), `.gitattributes` eklendi. 203 → 43 takip edilen dosya. |
| 2026-08-13 | ADIM 2 | ✅ Kamera izni: 3 durum (verildi / reddedildi / kalıcı red) ayrı ayrı ele alındı, ayarlardan dönüşte otomatik güncelleme çalışıyor. |
| 2026-08-13 | ADIM 3 | ✅ CameraX 1.4.1 + Preview. Canlı görüntü çalışıyor. `FIT_CENTER` kararı alındı. CameraX cheatsheet PDF olarak hazırlandı. |
| 2026-08-13 | ADIM 4 | ✅ ImageAnalysis + `FrameStats` (`:core`, 11 test). Referans: 29.8 FPS / p95 ≈ 0 ms. Kamera FPS'inin ışığa bağlı olduğu tespit edildi. `CoreMarker` silindi. |
| 2026-08-13 | ADIM 5 | ✅ ML Kit pose-detection 18.0.0-beta5, STREAM_MODE. `close()` asenkron akışa taşındı. 27.5 FPS / p95 33 ms. |
| 2026-08-13 | ADIM 6 | ✅ `ViewTransform` (`:core`, 10 test) + skeleton overlay. FIT_CENTER + aynalama. 20 FPS / p95 40 ms. |
| 2026-08-13 | ADIM 7 | ✅ `PoseFrame` `:core`'a taşındı. `LandmarkType` enum (17 nokta), Map yapısı, `timestampNanos`. `grep -r mlkit core/src/` boş. |
| 2026-08-13 | ADIM 8 | ✅ `PoseMath` (atan2, 16 test) + `PoseAngles` (elbow/knee/hip, 10 test). Toplam 58 test. Canlı dirsek açısı ekranda. |
| 2026-08-13 | ADIM 9 | ✅ `SideSelector` histerezisli (enter 0.15 / exit 0.10), `chainConfidence` = min. 71 test. Ekranda seçili taraf + iki güven. |
| 2026-08-14 | ADIM 10 | ✅ `NormalizationBasis` + `NormPoint` (:core, 86 test). N1-N6 + ölçek/çözünürlük değişmezliği. `torso_length` Double'da hesaplanıyor — Float `sqrt` sınır değerde (0.05) kapının yanlış tarafına düşüyordu. Çapa frame başına bir kez, landmark çevirimi istendiğinde (Map ayırmıyoruz). |
| 2026-08-14 | ADIM 11 | ✅ `OneEuroFilter` + `PoseSmoother` (:core, 109 test). E1-E5. Filtre **image-normalized** birimde çalışıyor (`beta` birime bağlı; pikselde 480p ve 1080p farklı davranırdı), çıktı piksele geri çevriliyor → ADIM 10 koduna dokunulmadı. Güvensiz landmark filtreyi beslemiyor; 500 ms üstü kesinti ve geriye giden timestamp → reset. |
| 2026-08-14 | ADIM 11+ | ⚠️ `pose-math` §6 türevi ham `x_prev`'den alıyor; orijinal One-Euro makalesi filtrelenmiş `x̂_prev` kullanıyor. Dokümandaki hâliyle implemente edildi (parity kuralı). Karar bekliyor. |
| 2026-08-14 | ADIM 15 | ✅ `RepFsm` + `RepFsmConfig` + `RepSummary` (:core, 193 test). 4 durum, histerezis `init` bloğunda zorunlu tutuluyor (eşitlenirse `IllegalArgumentException`). Kapı sırası: SIGNAL_LOST → INSUFFICIENT_ROM → TOO_FAST (derinlik tempodan daha temel sorun). Yarım iniş de kapılardan geçiyor. Sayılmayan tekrarlar `RepSummary` olarak dönüyor, atılmıyor. Bir frame = bir geçiş. |
| 2026-08-14 | ADIM 14 | ✅ `PersonalCalibration` + `CalibrationCollector` (:core, 169 test). 3 tekrar, **medyan** (ortalama değil — tek kötü tekrar bozmasın). Tavuk-yumurta: rep FSM kalibrasyona muhtaç olduğu için kalibrasyon FSM kullanmıyor, ham açı üzerinde mutlak 30°'lik salınım dedektörü ile önyükleme yapıyor. ROM < 40° → geçersiz. Sinyal kesintisi süre tabanlı (500 ms), tek frame düşmesi tolere ediliyor. `neutralHipOffset` cihaz ölçümüyle doğrulandı (-0.18). `:core` hazır, **UI akışı bağlanmadı**. |
| 2026-08-14 | ADIM 12-13 | ✅ **Cihaz doğrulaması yapıldı.** Setup Validator uçtan uca çalışıyor: diz üstü plankta `READY` (yeşil "Hazır"), önden çekimde `CA,IP` → "Telefonu yan tarafına koy", telefon sallanırken `CS` → "Telefon sallanıyor". Görüş bantları gerçek vücutta tutuyor (yandan `swRatio` 0.19-0.22, önden 0.60). `hipOff` işareti doğru (pike → negatif). `hipOff` kapısı düzeltildi ve ayakta duruşta `--` döndüğü doğrulandı. |
| 2026-08-14 | ADIM 13 | ✅ `SetupValidator` + `SetupConfig` + `shoulder_width_ratio` (:core, 152 test). 6 kontrol, enum sırası = gösterim önceliği. `:core` kullanıcı metni üretmiyor — enum döndürüyor, metinler `:app`'te `strings.xml`'e gidecek. Belirsiz görüş bandı (0.35-0.60) da reddediliyor. Drift 2 sn pencerede ortalama; pencere dolmadan karar verilmiyor. `SetupConfig(requiredView = FRONT)` testi motorun genel kaldığını doğruluyor. |
| 2026-08-14 | ADIM 12 | ✅ `PushUpFeatures` + `PushUpFeatureExtractor` (:core, 131 test). `elbow_angle`, `hip_vertical_offset` (işaretli), `torso_inclination`, `shoulder_velocity_y`. Her alan bağımsız nullable. Zincir `CameraPreview`'e bağlandı, iskelet artık smoothed pozdan çiziliyor, overlay 5 feature gösteriyor. Spec'te 3 tutarsızlık bulundu (yukarı bak). **Cihaz doğrulaması bekliyor.** |
