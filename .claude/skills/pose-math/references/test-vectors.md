# Pose Math — Test Vektörleri

Bu dosyadaki her vektör **Kotlin ve Python implementasyonlarında birden** koşar.
Tolerans: mutlak fark ≤ `1e-4`.

Yeni bir formül eklendiğinde en az bir vektör eklemek zorunludur. Vektörü olmayan formül
`SKILL.md`'ye giremez.

---

## 1. Açı Hesabı — `angle_at(A, B, C)`

| # | A | B | C | Beklenen (derece) | Ne test ediyor |
|---|---|---|---|---|---|
| A1 | (0, 0) | (1, 0) | (1, 1) | 90.0 | Dik açı |
| A2 | (0, 0) | (1, 0) | (2, 0) | 180.0 | Tam düz — `acos` burada NaN üretir |
| A3 | (0, 0) | (2, 0) | (3, 1.7320508) | 120.0 | Geniş açı, irrasyonel koordinat |
| A4 | (1, 1) | (0, 0) | (1, -1) | 90.0 | Negatif koordinatlı dik açı |
| A5 | (0, 0) | (1, 0) | (0.5, 0) | 0.0 | Üst üste binen vektörler — sıfır açı kararlılığı |
| A6 | (3, 4) | (0, 0) | (4, -3) | 90.0 | Ölçek değişmezliği (uzun vektörler) |

**A6 notu:** A1 ile aynı geometrik ilişki, 5× ölçek. Açının ölçek değişmez olduğunun kanıtı —
bu vektör geçmiyorsa normalizasyon yanlış yerde uygulanıyordur.

---

## 2. Eksene Göre Açı

### `angle_to_vertical(P, Q)`

| # | P | Q | Beklenen | Ne test ediyor |
|---|---|---|---|---|
| V1 | (0, 0) | (0, 1) | 0.0 | Tam dikey (aşağı) |
| V2 | (0, 0) | (1, 0) | 90.0 | Tam yatay |
| V3 | (0, 0) | (1, 1) | 45.0 | Diyagonal |
| V4 | (0, 0) | (-1, 1) | 45.0 | Mutlak değer — sol eğilim sağ ile aynı |
| V5 | (0, 0) | (0, -1) | 0.0 | Yukarı uzanan dikey de dikeydir |

### `angle_to_horizontal(P, Q)`

| # | P | Q | Beklenen | Ne test ediyor |
|---|---|---|---|---|
| H1 | (0, 0) | (1, 0) | 0.0 | Tam yatay (sağa) |
| H2 | (0, 0) | (0, 1) | 90.0 | Tam dikey |
| H3 | (0, 0) | (1, 1) | 45.0 | Diyagonal |
| H4 | (0, 0) | (-1, 0) | 0.0 | **Sola uzanan yatay da yataydır** |
| H5 | (0, 0) | (-1, 1) | 45.0 | Sol diyagonal sağ ile aynı |
| H6 | (400, 200) | (50, 210) | 1.637 | Gerçek gövde, sola uzanan |

**Değişmez:** her `P`, `Q` için `angle_to_horizontal(P,Q) == angle_to_horizontal(Q,P)`
ve `angle_to_horizontal + angle_to_vertical == 90`. Her ikisi de `[0, 90]` aralığında.

H4–H6 ve V5, sahada yakalanan bir hatadan sonra eklendi: eski vektörlerin tamamı
`dx >= 0` tarafındaydı ve hata testlerin hiç bakmadığı çeyrekte duruyordu.
Gerekçe: `SKILL.md` → "Bir vektörün eksene göre açısı".

---

## 3. Normalization

### Girdi iskeleti (image-normalized koordinat, `x/h` ve `y/h`)

```
LEFT_SHOULDER  = (0.40, 0.30)
RIGHT_SHOULDER = (0.60, 0.30)
LEFT_HIP       = (0.45, 0.55)
RIGHT_HIP      = (0.55, 0.55)
```

### Beklenen ara değerler

| Değer | Beklenen |
|---|---|
| `mid_shoulder` | (0.50, 0.30) |
| `mid_hip` | (0.50, 0.55) |
| `torso_length` | 0.25 |

### Normalize koordinat dönüşümü

| # | Girdi noktası | Beklenen `(x_norm, y_norm)` | Ne test ediyor |
|---|---|---|---|
| N1 | (0.50, 0.55) | (0.0, 0.0) | Origin = mid_hip |
| N2 | (0.50, 0.30) | (0.0, -1.0) | Omuz tam 1 torso yukarıda (y aşağı arttığı için negatif) |
| N3 | (0.75, 0.55) | (1.0, 0.0) | Yatay ölçek |
| N4 | (0.50, 0.80) | (0.0, 1.0) | Aşağı yön pozitif |

**N2 kritik:** işareti ters çıkıyorsa `y` ekseni yönü yanlış anlaşılmıştır. Bu hata tüm
"derinlik" ve "kalça yüksekliği" kurallarını sessizce ters çevirir.

### Ölçek değişmezliği testi

Aynı iskelet 2× büyütülüp (0.1, 0.1) ötelendiğinde **tüm `x_norm`/`y_norm` değerleri
değişmemelidir.**

```
LEFT_SHOULDER  = (0.90, 0.70)
RIGHT_SHOULDER = (1.30, 0.70)
LEFT_HIP       = (1.00, 1.20)
RIGHT_HIP      = (1.20, 1.20)
torso_length   = 0.50
```
N1–N4'ün 2×+öteleme karşılıkları aynı sonucu vermelidir. Bu test, normalizasyonun gerçekten
kullanıcı boyundan ve kamera mesafesinden bağımsız olduğunun kanıtıdır.

### Geçerlilik kapısı

| # | `torso_length` | Beklenen |
|---|---|---|
| N5 | 0.04 | tüm normalize feature'lar `null` |
| N6 | 0.05 | hesaplanır (sınır dahil) |

---

## 4. Confidence Gating

Feature: `elbow_angle`, bağlı landmark'lar `[SHOULDER, ELBOW, WRIST]`

| # | shoulder | elbow | wrist | Beklenen |
|---|---|---|---|---|
| C1 | 0.9 | 0.9 | 0.9 | hesaplanır |
| C2 | 0.9 | 0.9 | 0.49 | `null` |
| C3 | 0.5 | 0.5 | 0.5 | hesaplanır (sınır dahil) |
| C4 | 0.9 | 0.3 | 0.9 | `null` |

---

## 5. One-Euro Filter

Determinizm testi — sabit girdi:

| # | Senaryo | Beklenen |
|---|---|---|
| E1 | İlk örnek `x=1.0` | çıktı `1.0` (durum yok, girdi aynen geçer) |
| E2 | 10 ardışık `x=1.0`, dt=0.0667 | çıktı `1.0` (±1e-6) — sabit girdide sapma olmamalı |
| E3 | `x` 0.0 → 1.0 basamak, dt=0.0667 | çıktı monoton artan, asla overshoot yok |
| E4 | Aynı girdi dizisi iki kez, arada reset | iki çalıştırma birebir aynı |

**E4 kritik:** filtre durumu sızıyorsa aynı girdi farklı çıktı verir; bu, Kotlin ve Python
arasındaki parity farklarının en sinsi kaynağıdır.

### Değişken dt testi

| # | Senaryo | Beklenen |
|---|---|---|
| E5 | dt = 0.0667 sabit vs dt = [0.0667, 0.133, 0.0667] değişken, aynı x dizisi | **farklı çıktı** |

E5 bir "geçmesi gereken" test değil, bir **kanıt testi**: çıktılar aynı çıkıyorsa
implementasyon `dt`'yi kullanmıyor, sabit FPS varsayıyordur → hata.

---

## 6. Taraf Seçimi

| # | sol conf | sağ conf | Beklenen |
|---|---|---|---|
| S1 | 0.90 | 0.40 | sol taraf |
| S2 | 0.40 | 0.90 | sağ taraf |
| S3 | 0.80 | 0.75 | ortalama (fark 0.05 < 0.15) |
| S4 | 0.80 | 0.64 | sol taraf (fark 0.16 > 0.15) |
| S5 | 0.80 → 0.40 rep ortasında | rep boyunca **sol** kalır | Taraf kilitleme |

---

## 7. Uçtan Uca Vektör — Push-Up Kolu

Gerçekçi bir iskelet parçası (image-normalized), yan görüş:

```
SHOULDER = (0.50, 0.40)
ELBOW    = (0.62, 0.48)
WRIST    = (0.62, 0.62)
HIP      = (0.35, 0.45)
KNEE     = (0.20, 0.47)
```

| Feature | Beklenen (derece, ±0.01) | Not |
|---|---|---|
| `elbow_angle` = angle_at(SHOULDER, ELBOW, WRIST) | 123.69 | |
| `body_line_angle` = angle_at(SHOULDER, HIP, KNEE) | 169.16 | ~düz gövde |

Bu vektör hem açı formülünü hem landmark seçimini birlikte test eder; birim testlerin
geçip entegrasyonun bozulduğu durumu yakalar.

---

## Vektör Ekleme Kuralı

1. Formül `SKILL.md`'ye eklendi mi? Eklenmedi ise önce oraya.
2. En az bir **normal** ve bir **sınır/dejenere** vektör yaz.
3. Beklenen değeri elle hesapla — implementasyonun çıktısını kopyalama.
   (Implementasyondan üretilen "beklenen değer" hiçbir şeyi test etmez.)
