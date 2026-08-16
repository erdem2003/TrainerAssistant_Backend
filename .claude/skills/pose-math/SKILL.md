---
name: pose-math
description: Pose landmark matematiğinin tek doğruluk kaynağı — landmark haritası, confidence gating, normalization, açı/mesafe/hız formülleri ve One-Euro smoothing. Bir feature hesaplanacaksa, bir formül Kotlin veya Python'da yazılacaksa ya da iki taraf arasında sayısal fark görüldüğünde kullan.
---

# Pose Math — Tek Doğruluk Kaynağı

Bu dosyadaki her formül **iki dilde birden** implemente edilecek: Kotlin (Android, gerçek zamanlı)
ve Python (offline feature extraction, model eğitimi). İki implementasyon aynı girdide aynı
çıktıyı vermek zorundadır.

> **Parity kuralı:** Bir formül değişiyorsa önce bu dosya güncellenir, `references/test-vectors.md`'ye
> yeni vektör eklenir, sonra her iki implementasyon güncellenir. Tek tarafı düzeltmek yasaktır.
> İki taraf ayrışırsa model, production'da eğitildiğinden farklı veri görür — bu tür projelerin
> en sık ve en sessiz ölüm sebebidir.

---

## 1. Landmark Haritası

ML Kit Pose Detection (full body) **33 landmark** döndürür. İndeksler MediaPipe BlazePose
sıralamasıyla aynıdır.

| # | İsim | # | İsim | # | İsim |
|---|---|---|---|---|---|
| 0 | NOSE | 11 | LEFT_SHOULDER | 22 | RIGHT_THUMB |
| 1 | LEFT_EYE_INNER | 12 | RIGHT_SHOULDER | 23 | LEFT_HIP |
| 2 | LEFT_EYE | 13 | LEFT_ELBOW | 24 | RIGHT_HIP |
| 3 | LEFT_EYE_OUTER | 14 | RIGHT_ELBOW | 25 | LEFT_KNEE |
| 4 | RIGHT_EYE_INNER | 15 | LEFT_WRIST | 26 | RIGHT_KNEE |
| 5 | RIGHT_EYE | 16 | RIGHT_WRIST | 27 | LEFT_ANKLE |
| 6 | RIGHT_EYE_OUTER | 17 | LEFT_PINKY | 28 | RIGHT_ANKLE |
| 7 | LEFT_EAR | 18 | RIGHT_PINKY | 29 | LEFT_HEEL |
| 8 | RIGHT_EAR | 19 | LEFT_INDEX | 30 | RIGHT_HEEL |
| 9 | LEFT_MOUTH | 20 | RIGHT_INDEX | 31 | LEFT_FOOT_INDEX |
| 10 | RIGHT_MOUTH | 21 | LEFT_THUMB | 32 | RIGHT_FOOT_INDEX |

Bu projede **yalnızca şu 17 landmark kullanılır** (11–16, 23–32 ve 0):
gövde, kollar, bacaklar, ayaklar + burun (baş pozisyonu).
Yüz ve el detay landmark'ları (1–10, 17–22) hiçbir feature'da kullanılmaz.

### Koordinat sistemi — dikkat

- ML Kit **görüntü koordinatı** döndürür: `x` sağa, **`y` AŞAĞI doğru artar.**
- Bu yüzden "kalça dizin üstünde" koşulu `hip.y < knee.y` şeklindedir. Ters yazmak
  en kolay yapılan hatadır; her yükseklik karşılaştırmasına yorum satırı düş.
- `z` **kullanılmaz.** Metrik derinlik değildir, kalçaya göre görelidir ve güvenilmezdir.
  Yalnızca dataset'e loglanır.
- Ön kamera kullanılırsa görüntü aynalanır → `x` ekseni ters döner. Sol/sağ landmark'lar
  kullanıcının gerçek sol/sağı olmayabilir. Bu projede **arka kamera varsayılır**; ön kamera
  desteklenirse aynalama feature hesabından ÖNCE düzeltilir.

---

## 2. Confidence Gating

```
CONFIDENCE_THRESHOLD = 0.5
```

Bir feature'ın bağlı olduğu landmark'lardan **herhangi biri** `inFrameLikelihood < 0.5` ise:

```
feature = null
```

Kesin kurallar:
- `null` yerine varsayılan/son bilinen değer **atanmaz**
- `null` feature ile hiçbir kural değerlendirilmez, hiçbir sesli uyarı verilmez
- Faz sinyali (`p`) `null` olursa rep state machine `HOLD` durumuna geçer, state değiştirmez
- Bir rep boyunca faz sinyali toplam **> 200 ms** kesintiye uğrarsa o rep **geçersiz** sayılır

Setup Validator için daha yüksek eşik kullanılır: `SETUP_THRESHOLD = 0.6`

---

## 3. Normalization

Üç aşamalı, sırası önemli.

### Adım 1 — Cihaz bağımsızlığı (piksel → oran)

```
x_img = x_px / image_height
y_img = y_px / image_height
```

`image_width` değil `image_height` ile bölünür — böylece en-boy oranı korunur ve
farklı çözünürlükler aynı sayıları üretir.

### Adım 2 — Smoothing

One-Euro filter, `x_img` ve `y_img` üzerine ayrı ayrı uygulanır (Bölüm 6).
**Smoothing normalizasyondan ÖNCE yapılır**, çünkü normalizasyon çapası (kalça/omuz) de
gürültülüdür; önce ham koordinatı sakinleştirmek çapa titremesinin tüm feature'lara
yayılmasını önler.

### Adım 3 — Vücut-göreli koordinat

```
mid_shoulder = (LEFT_SHOULDER + RIGHT_SHOULDER) / 2
mid_hip      = (LEFT_HIP + RIGHT_HIP) / 2

torso_length = distance(mid_shoulder, mid_hip)

x_norm = (x_img - mid_hip.x) / torso_length
y_norm = (y_img - mid_hip.y) / torso_length
```

Sonuç: **hip-centered, torso-length ölçekli** koordinat. Kullanıcının boyundan, kameraya
uzaklığından ve kadrajdaki konumundan bağımsız.

**Geçerlilik kapısı:** `torso_length < 0.05` ise (kişi çok uzak veya landmark bozuk)
tüm normalize feature'lar `null` döner.

### Neden bu yöntem — reddedilen alternatifler

| Alternatif | Neden reddedildi |
|---|---|
| Shoulder width scaling | Yan görüşte omuzlar üst üste biner, ölçek çöker |
| Bounding box scaling | Uzuv pozisyonuna bağlı; kişi kolunu açınca ölçek değişir |
| Ham piksel | Cihaz, çözünürlük ve mesafeye bağımlı — hiçbir eşik taşınamaz |

Torso uzunluğu harekete en az bağımlı vücut ölçüsüdür. Push-up'ta bile omuz-kalça mesafesi
neredeyse sabittir.

---

## 4. Açı Hesabı

Üç nokta A, B, C için **B'deki açı**:

```
v1 = A - B
v2 = C - B

cross = v1.x * v2.y - v1.y * v2.x
dot   = v1.x * v2.x + v1.y * v2.y

angle_rad = atan2(|cross|, dot)
angle_deg = angle_rad * 180 / PI        →  [0, 180]
```

**`acos(dot / (|v1| * |v2|))` KULLANMA.** 0° ve 180° civarında sayısal olarak kararsızdır
ve kayan nokta hatasıyla domain dışına çıkıp `NaN` üretir. `atan2` her aralıkta kararlıdır.

Açılar **ölçek ve öteleme değişmezdir** — normalize koordinatta da ham koordinatta da aynı
sonucu verir. Bu yüzden açı feature'ları için normalizasyon zorunlu değildir (ama
tutarlılık için hep normalize koordinat kullanılır).

### Bir vektörün eksene göre açısı

```
fold(a)                   = a if a <= 90 else 180 - a                    →  [0, 90]

angle_to_vertical(P, Q)   = fold(|atan2(Q.x - P.x, Q.y - P.y)| * 180 / PI)
angle_to_horizontal(P, Q) = fold(|atan2(Q.y - P.y, Q.x - P.x)| * 180 / PI)
```

Sonuç **[0, 90]** aralığındadır ve **yönsüzdür**: vektörün hangi ucundan ölçüldüğü
sonucu değiştirmez. Bir *eksene göre* açı sorulurken istenen budur — gövde "yatay"
ise sola da uzansa sağa da uzansa yataydır.

> **`fold` neden var — bu bir hata düzeltmesidir (2026-08-15).**
> Önceki spec yalnızca `abs` alıyor ve `[0, 180]` diyordu. `abs` yukarı/aşağı ayrımını
> siler ama **sağ/sol ayrımını silmez**:
>
> | Gövde | P → Q | Eski | Yeni |
> |---|---|---|---|
> | sağa uzanan | omuz(400,200) → ayak(50,210) | 1.6° | 1.6° |
> | sola uzanan | omuz(50,200) → ayak(400,210) | **178.4°** | 1.6° |
>
> İkisi de yatay bir gövde. Kullanıcı kameraya göre ters yöne döndüğünde
> `torso_inclination` ~180 çıkıyor, `max_torso_inclination = 35` kapısına takılıyor ve
> Setup Validator şınavı hiç başlatmıyordu. Offline etiketleyici de aynı sebeple 78
> kaydın bütün karelerini `NOT_PUSHUP` saydı — veri setinde tek bir `TOP`/`BOTTOM`
> örneği oluşmadı.
>
> Hatanın gözden kaçma sebebi: hem spec vektörleri (V1–V4, H1–H3) hem birim testler
> yalnızca `dx >= 0` tarafını kapsıyordu. `fold` o vektörlerin hiçbirini değiştirmez.

---

## 5. Mesafe ve Yükseklik Farkı

```
distance(P, Q)      = sqrt((Q.x - P.x)^2 + (Q.y - P.y)^2)      // normalize koordinatta
height_delta(P, Q)  = Q.y - P.y                                 // POZİTİF = P, Q'nun ÜSTÜNDE
```

`height_delta` yorumunda dikkat: `y` aşağı arttığı için `hip.y - knee.y` negatifse
kalça dizin **üstündedir**. Feature adları bu kafa karışıklığını önleyecek şekilde seçilir
(ör. `hip_above_knee_norm` gibi yön belirten isimler kullan).

---

## 6. One-Euro Filter

Basit EMA yerine One-Euro kullanılır. Sebep: EMA'da gürültüyü azaltmak gecikmeyi artırır.
One-Euro **düşük hızda çok filtreler, yüksek hızda az filtreler** — durağan pozda stabil,
hızlı harekette gecikmesiz. Bu tam olarak egzersiz analizinin ihtiyacıdır.

```
alpha(cutoff, dt) = 1 / (1 + tau/dt),   tau = 1 / (2*PI*cutoff)

# her yeni örnek (x, t) için:
dt      = t - t_prev                                  # saniye, GERÇEK timestamp'ten
dx      = (x - x_prev) / dt
dx_hat  = alpha(d_cutoff, dt) * dx + (1 - alpha(d_cutoff, dt)) * dx_hat_prev
cutoff  = min_cutoff + beta * |dx_hat|
x_hat   = alpha(cutoff, dt) * x + (1 - alpha(cutoff, dt)) * x_hat_prev
```

**Başlangıç parametreleri** (Phase 2'de gerçek kayıtla kalibre edilecek — bunlar nihai değer değil):

```
min_cutoff = 1.0   Hz
beta       = 0.5
d_cutoff   = 1.0   Hz
```

Kurallar:
- `dt` **gerçek frame timestamp'inden** hesaplanır, sabit FPS varsayılmaz. Frame düşerse
  sabit dt kullanmak filtreyi bozar.
- Her landmark'ın x ve y'si için **ayrı filtre durumu** tutulur (33 × 2 = 66 filtre).
- Landmark `null`/düşük güvenli geldiğinde filtre **güncellenmez ve durumu bozulmaz**;
  kesinti > 500 ms sürerse filtre sıfırlanır.

---

## 7. Türev Sinyaller (hız / ivme)

```
velocity(t) = (signal_hat(t) - signal_hat(t-1)) / dt        # birim: norm-birim / saniye
```

- Türev **her zaman smoothed sinyalden** alınır. Ham sinyalden türev almak gürültüyü büyütür.
- `dt` gerçek timestamp farkıdır.
- İvme MVP'de kullanılmaz; gerekirse hızın One-Euro ile tekrar filtrelenmiş türevi alınır.
  İki kez türev = gürültünün karesi, çok dikkatli kullanılmalı.

---

## 8. Taraf Seçimi (Side Selection)

Yan görüşte bir taraf diğerini kapatır. Politika:

```
her taraf için: side_confidence = min(ilgili landmark'ların inFrameLikelihood değerleri)

if |sol - sağ| > 0.15   → yüksek olan taraf kullanılır
else                    → iki tarafın ortalaması kullanılır
```

- Seçilen taraf **rep boyunca sabit kalır** (rep ortasında taraf değiştirmek sinyalde
  sıçrama yaratır ve sahte state geçişi üretir).
- Hangi tarafın kullanıldığı dataset'e `used_side` alanı olarak yazılır.
- Asimetri tespiti gerektiren feature'lar (ör. squat `ASYMMETRY`) bu kuralın dışındadır;
  onlar iki tarafı da ister ve biri güvensizse `null` döner.

---

## 9. Parity Testi

`references/test-vectors.md` içindeki her vektör, iki implementasyonda da çalıştırılır.

- Tolerans: **1e-4** (mutlak fark)
- Kotlin tarafı: saf JVM unit test (Android bağımlılığı yok)
- Python tarafı: pytest
- Test vektörleri CI'da her iki tarafta koşar (Phase 13'ten itibaren)
- Bir vektör tutmuyorsa: **implementasyonu bu dokümana uydur**, dokümanı implementasyona değil

---

## 10. Yasaklar

- `z` koordinatı kullanmak
- `acos` ile açı hesaplamak
- Sabit FPS varsayarak `dt` hesaplamak
- Düşük güvenli landmark'a varsayılan değer atamak
- Piksel cinsinden eşik yazmak
- Formülü tek dilde değiştirmek
