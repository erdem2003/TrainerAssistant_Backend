# Feature Spec — Merkezi Kayıt

Tüm feature'ların **tek tanım yeri**. Egzersiz spec'leri buradan seçim yapar, burada
yeniden tanımlamaz.

Matematik: `.claude/skills/pose-math/SKILL.md` · Test vektörleri: `references/test-vectors.md`

> Yeni feature eklemeden önce: mevcut bir feature ile yüksek korelasyonlu mu? Ek bir hata
> ayırt ediyor mu? Cevap hayırsa **ekleme**. Feature enflasyonu hem frame bütçesini hem
> ML'de örnek/özellik oranını bozar.

Tüm hesaplar **normalize koordinatta** yapılır (hip-centered, torso-length ölçekli).
Tüm feature'lar bağlı landmark'lardan biri `inFrameLikelihood < 0.5` ise `null` döner.

---

## 1. Özet Tablo

| Feature | Birim | Görüş | Kullanan |
|---|---|---|---|
| `torso_length` | norm | ANY | setup, normalization |
| `shoulder_width_ratio` | oran | ANY | setup (görüş tespiti) |
| `elbow_angle` | derece | ANY | push-up: faz sinyali |
| `knee_angle` | derece | ANY | squat: faz sinyali |
| `hip_angle` | derece | ANY | squat: hip hinge |
| `hip_vertical_offset` | norm (işaretli) | SIDE | push-up: sag/pike |
| `torso_inclination` | derece | SIDE | push-up: plank bütünlüğü, setup |
| `torso_angle_vertical` | derece | SIDE | squat: öne eğilme |
| `hip_above_knee` | norm (işaretli) | SIDE | squat: derinlik |
| `elbow_flare` | norm | FRONT | push-up: dirsek açıklığı |
| `knee_valgus` | norm | FRONT | squat: diz içe kaçması |
| `heel_lift` | norm | SIDE | squat: topuk kalkması |
| `wrist_shoulder_offset` | norm (işaretli) | SIDE | push-up: el pozisyonu (setup) |
| `shoulder_velocity_y` | norm/s | ANY | push-up: tempo |
| `hip_velocity_y` | norm/s | ANY | squat: tempo |
| `side_asymmetry` | derece | FRONT | squat: sol/sağ farkı |
| `camera_drift` | norm/s | ANY | setup: telefon sabit mi |

---

## 2. Tanımlar

### `torso_length`
```
distance(mid_shoulder, mid_hip)     # image-normalized koordinatta, ölçekleme ÖNCESİ
```
Tüm normalizasyonun ölçek referansı. `< 0.05` → tüm normalize feature'lar `null`.
Setup'ta mesafe kontrolü için de kullanılır.

### `shoulder_width_ratio`
```
distance(LEFT_SHOULDER, RIGHT_SHOULDER) / torso_length
```
**Görüş tespitinin ana aracı.** Ön görüşte omuzlar tam açık, yan görüşte üst üste biner.

| Değer | Yorum |
|---|---|
| > 0.60 | FRONT |
| < 0.35 | SIDE |
| arası | belirsiz → setup uyarısı |

Bantlar `initial`, Phase 2'de gerçek kayıtla kalibre edilecek.

### `elbow_angle`
```
angle_at(SHOULDER, ELBOW, WRIST)      # seçilen taraf
```
Birim: derece [0, 180]. Kol tam düz ≈ 180.

### `knee_angle`
```
angle_at(HIP, KNEE, ANKLE)            # seçilen taraf
```
Ayakta ≈ 175-180, parallel squat ≈ 90, derin ≈ 60-70.

### `hip_angle`
```
angle_at(SHOULDER, HIP, KNEE)         # seçilen taraf
```
Squat'ta hip hinge kalitesi; push-up'ta gövde düzlüğünün **ikincil** göstergesi.

> Push-up'ta gövde sapması için `hip_angle` **yeterli değildir**: hem sarkma hem
> yukarı kalkma açıyı 180'den uzaklaştırır, ikisi ayırt edilemez. Bu yüzden
> `hip_vertical_offset` tanımlandı.

### `hip_vertical_offset` ⚠️ işaretli
```
line_y = SHOULDER.y + (HIP.x - SHOULDER.x) * (KNEE.y - SHOULDER.y) / (KNEE.x - SHOULDER.x)
hip_vertical_offset = (HIP.y - line_y) / torso_length
```
Kalçanın, omuz→diz doğrusuna göre **dikey** sapması.

```
> 0  →  kalça çizginin ALTINDA  →  SARKMA (sag)      [y aşağı artar]
< 0  →  kalça çizginin ÜSTÜNDE  →  YUKARI KALKMA (pike)
```

**Neden dikey sapma, dik (perpendicular) sapma değil:** dik sapmanın işareti kullanıcının
hangi yöne baktığına göre değişir (cross product yön değiştirir). Dikey sapma yerçekimi
yönüne dayanır ve yön bağımsızdır. Telefonun dik tutulduğu setup validator tarafından
zaten garanti edilir.

`|KNEE.x - SHOULDER.x| < 0.1` ise (gövde neredeyse dikey, push-up pozisyonu değil) → `null`.

### `torso_inclination`
```
angle_to_horizontal(mid_shoulder, mid_ankle)
```
Push-up'ta gövdenin yatayla açısı. 0'a yakın = doğru plank pozisyonu.
Setup doğrulamasında "kişi gerçekten push-up pozisyonunda mı" kontrolü.

### `torso_angle_vertical`
```
angle_to_vertical(mid_hip, mid_shoulder)
```
Squat'ta gövdenin dikeyle açısı. 0 = tam dik, artan = öne eğilme.

### `hip_above_knee` ⚠️ işaretli
```
hip_above_knee = (KNEE.y - HIP.y) / torso_length
```
```
> 0  →  kalça dizin ÜSTÜNDE (henüz parallel'e inilmedi)
= 0  →  parallel
< 0  →  parallel altı (derin squat)
```
**Squat derinliğinin asıl ölçütü.** `knee_angle` tek başına yanıltıcıdır: uzun femurlu bir
kullanıcı aynı diz açısında daha az derinliğe iner.

### `elbow_flare` — FRONT
```
elbow_flare = |ELBOW.x - SHOULDER.x| / torso_length
```
Dirseğin gövdeden yanal uzaklığı. SIDE görüşte `null`.

### `knee_valgus` — FRONT
```
hip_width  = distance(LEFT_HIP, RIGHT_HIP)
knee_valgus = (distance(LEFT_KNEE, RIGHT_KNEE) - hip_width) / hip_width
```
Negatif = dizler kalçadan dar → içe kaçma (valgus). SIDE görüşte `null`.
İki taraf da güvenilir olmalı; biri `< 0.5` ise `null`.

### `heel_lift` ⚠️ düşük güven
```
heel_lift = (FOOT_INDEX.y - HEEL.y) / torso_length
```
Pozitif = topuk parmaklardan yukarıda → topuk kalkmış.
ML Kit'in ayak landmark'ları gövdeye göre daha gürültülü → **yalnızca uyarı seviyesinde**
kullanılır, rep'i geçersiz kılmaz. Eşik geniş tutulur.

### `wrist_shoulder_offset` ⚠️ işaretli
```
wrist_shoulder_offset = (WRIST.x - SHOULDER.x) / torso_length
```
Push-up setup kontrolü: el bileği omuz hizasında mı. Pozitif/negatif yön kullanıcının
baktığı yöne bağlı → **mutlak değeri** kullanılır.

### `shoulder_velocity_y` / `hip_velocity_y`
```
velocity = (signal_hat(t) - signal_hat(t-1)) / dt      # norm-birim / saniye
```
Smoothed sinyalden, gerçek `dt` ile. Tempo, eccentric/concentric ayrımı ve kontrol
değerlendirmesi için.

### `side_asymmetry` — FRONT
```
side_asymmetry = |left_knee_angle - right_knee_angle|
```
Squat'ta sol/sağ yük dengesizliği. İki taraf da güvenilir olmalı.

### `camera_drift`
```
camera_drift = distance(mid_hip(t), mid_hip(t-1)) / dt     # smoothed, image-norm koordinatta
```
Setup'ta telefonun sabit olup olmadığını kontrol eder. Kullanıcı hareketsizken yüksek
değer = telefon sallanıyor.

---

## 3. Feature Kullanım Matrisi

| Feature | Push-Up | Squat |
|---|---|---|
| `elbow_angle` | faz sinyali | — |
| `knee_angle` | — | faz sinyali |
| `hip_vertical_offset` | sag / pike | — |
| `hip_above_knee` | — | derinlik |
| `torso_inclination` | plank + setup | — |
| `torso_angle_vertical` | — | öne eğilme |
| `hip_angle` | — | hip hinge |
| `elbow_flare` | dirsek açıklığı (FRONT) | — |
| `knee_valgus` | — | valgus (FRONT) |
| `heel_lift` | — | topuk (uyarı) |
| `wrist_shoulder_offset` | setup | — |
| `shoulder_velocity_y` | tempo | — |
| `hip_velocity_y` | — | tempo |
| `side_asymmetry` | — | asimetri (FRONT) |
| `shoulder_width_ratio` | setup | setup |
| `camera_drift` | setup | setup |

---

## 3.5. Rep-Level Aggregate'ler

Frame-level feature'lardan **rep tamamlandığında** türetilir. `phase: REP_END` hataları ve
(Phase 8'den itibaren) ML modelinin girdisi bunlardır.

| Aggregate | Hesap | Kullanan |
|---|---|---|
| `rep_duration_s` | rep başlangıcı → bitişi | FSM kapıları, tempo |
| `rep_eccentric_duration_s` | `DESCENDING` + `BOTTOM` süresi | `TOO_FAST` |
| `rep_concentric_duration_s` | `ASCENDING` süresi | tempo, TUT |
| `rep_rom` | rep içi `max(p) - min(p)` | FSM kapısı `min_rom` |
| `phase_signal_min` / `_max` | rep içi faz sinyali uçları | `PARTIAL_LOCKOUT`, `INCOMPLETE_EXTENSION` |
| `<feature>_min` / `_max` / `_mean` | ilgili feature'ın rep içi istatistiği | hata koşulları |
| `<feature>_variance` | rep içi varyans | ML: kontrol/stabilite göstergesi |
| `velocity_peak` / `velocity_profile` | hız tepe değeri ve normalize profil özeti | ML: `LOSS_OF_CONTROL` |

Kurallar:
- Aggregate'ler **yalnızca geçerli** (`null` olmayan) frame'lerden hesaplanır
- Rep boyunca geçerli frame oranı `< %80` ise tüm aggregate'ler `null` → rep ML'e verilmez
- Süre ölçümleri gerçek frame timestamp'lerinden gelir, frame sayısından değil

## 4. Bilinçli Olarak Tanımlanmayanlar

| Aday | Neden yok |
|---|---|
| `shoulder_angle` (elbow-shoulder-hip) | `elbow_angle` ile yüksek korelasyon, ek hata ayırt etmiyor |
| Tüm `z` tabanlı feature'lar | ML Kit `z` güvenilmez (ADR 0004, pose-math §1) |
| `limb_ratios` (uzuv oranları) | Kişisel kalibrasyona taşındı — her frame hesaplamanın anlamı yok |
| `acceleration` | İki kez türev = gürültünün karesi. Gerekirse Phase 8'de, çift filtrelemeyle |
| `head_position` / `neck_angle` | Push-up'ta baş düşmesi gerçek bir hata ama ML Kit burun landmark'ı yandan güvenilmez. Phase 8'de yeniden değerlendirilecek |
| `bar_path` / center of mass | Ağırlıksız vücut egzersizlerinde karşılığı zayıf |

---

## 5. ML'e Aday Hata Sınıfları

Rule engine'in yapısal olarak ayırt **edemediği** durumlar. Bu liste Phase 8'de
ML'e geçişin gerekçe belgesidir — dolduruldukça büyür.

| Hata | Neden kuralla olmuyor | Gerekecek feature'lar |
|---|---|---|
| `LOSS_OF_CONTROL` | Tek eşik değil; hız profili + varyans + asimetrinin zaman içindeki ortak paterni. Eşikle yazınca ya çok hassas ya çok kör | `velocity_profile`, `angle_variance`, `side_asymmetry` |
| `COMPENSATION_PATTERN` | Kullanıcı bir zayıflığı başka bir eklemle telafi ediyor; hiçbir tek feature eşiği bunu görmüyor, ilişki çok değişkenli | çoklu eklem açıları + zaman |
| `OVERALL_QUALITY` | Öznel "iyi rep" algısı; elle ağırlıklandırma keyfi kalıyor | tüm rep-level aggregate'ler |
| `FATIGUE_ONSET` | Rule ile trend olarak yakalanabiliyor (ROM/tempo düşüşü) ama başlangıç noktası bulanık | set içi rep dizisi |

> `FATIGUE_ONSET` şu an rule ile **yeterince iyi** çalışıyor kabul ediliyor (ROM ve tempo
> düşüş trendi). ML'e ancak rule versiyonu sahada yetersiz kalırsa taşınır.
