---
name: exercise-spec
description: Bir egzersizin makine-okunur spesifikasyon formatı — gerekli kamera görüşü, feature listesi, faz sinyali, rep state machine eşikleri, form hataları ve sesli feedback metinleri. Yeni egzersiz eklenecekse, bir eşik değiştirilecekse veya rep sayma mantığı tartışılacaksa kullan.
---

# Exercise Spec Formatı

Bu projede **egzersiz motoru geneldir, egzersizler veridir.** Push-up'a özel bir `if`
yazılmaz. Yeni egzersiz eklemek = yeni bir spec yazmak.

> Motor dosyası bir egzersiz eklerken değişiyorsa, tasarım yanlıştır — motora değil,
> spec formatına eksik gelen bir alan vardır. Format eksikse bu dosya güncellenir.

Şablon: `references/template.md`
Yazılmış spec'ler: `docs/computer-vision/pushup.md`, `docs/computer-vision/squat.md`

---

## 1. Spec'in Bölümleri

| Bölüm | Ne tanımlar |
|---|---|
| `meta` | id, isim, kategori, desteklenen görüşler |
| `setup` | kamera kurulumu koşulları — bunlar sağlanmadan rep sayılmaz |
| `features` | bu egzersizin kullandığı feature'lar (pose-math referansıyla) |
| `phase_signal` | rep state machine'i süren tek boyutlu sinyal `p ∈ [0,1]` |
| `rep_fsm` | histerezis eşikleri ve geçerlilik kapıları |
| `calibration` | kişisel kalibrasyonda ne ölçülür, hangi eşikler buna bağlanır |
| `errors` | form hataları, tetiklenme koşulları, öncelik, feedback metinleri |
| `ml_candidates` | rule engine'in ayırt edemediği, ML'e aday hata sınıfları |

---

## 2. Faz Sinyali — Motorun Kalbi

Her egzersiz hareketini tek bir normalize sayıya indirger:

```
p = 1.0  →  hareketin ÜST/başlangıç noktası (push-up: kol düz, squat: ayakta)
p = 0.0  →  hareketin ALT/bitiş noktası (kişisel kalibrasyona göre)
```

Tanımı:
```
p = clamp( (raw_signal - p_min_cal) / (p_max_cal - p_min_cal), 0.0, 1.0 )
```

`p_min_cal` ve `p_max_cal` **kişisel kalibrasyondan** gelir, sabit değildir. Bu sayede
esnek olmayan bir kullanıcının %100'ü ile esnek bir kullanıcının %100'ü aynı `p` değerini üretir.

**Egzersize özel olan tek şey `raw_signal`'in nasıl hesaplandığıdır.** Geri kalan motor ortaktır.

| Egzersiz | `raw_signal` |
|---|---|
| Push-up | `elbow_angle` |
| Squat | `knee_angle` |
| Sit-up | `hip_angle` |
| Plank | *(yok — plank rep tabanlı değil, süre tabanlıdır; ayrı mod)* |

> **Plank uyarısı:** İzometrik egzersizler bu motora girmez. Onlar için `hold_fsm` gerekir
> (süre + form stabilitesi). Format bunu Phase 5'te kazanacak; şimdi kapsam dışı.

---

## 3. Rep State Machine

Ortak, egzersizden bağımsız. Yalnızca eşikler spec'ten gelir.

```
        p > exit_top
   ┌──────────────────────────────┐
   │                              │
   ▼         p < enter_descend    │
  TOP ──────────────────────────► DESCENDING
                                     │ p < enter_bottom
                                     ▼
   TOP ◄────────────────── ASCENDING ◄── BOTTOM
        p > exit_top   │              p > exit_bottom
                       │
                  emit RepCompleted
```

### Histerezis — zorunlu

Her geçişin giriş ve çıkış eşiği **farklı** olmalıdır:

```
enter_descend = 0.85      # TOP'tan çıkış
exit_top      = 0.90      # TOP'a dönüş  → 0.05 boşluk
enter_bottom  = 0.30      # BOTTOM'a giriş
exit_bottom   = 0.40      # BOTTOM'dan çıkış → 0.10 boşluk
```

Tek eşik kullanılırsa kullanıcı eşiğin tam üstünde titrediğinde sayaç saniyede birkaç kez
artar. Bu, rep sayan uygulamaların en yaygın hatasıdır.

### Geçerlilik kapıları

`ASCENDING → TOP` geçişinde rep sayılmadan önce kontrol edilir:

| Kapı | Varsayılan | Sağlanmazsa |
|---|---|---|
| `min_duration_s` | 0.4 | `PARTIAL_REP` olarak loglanır, sayılmaz |
| `max_duration_s` | 10.0 | rep iptal, state `TOP`'a sıfırlanır |
| `min_rom` | 0.55 | `PARTIAL_REP` — yeterli derinliğe inilmedi |
| `signal_gap_ms` | 200 | rep geçersiz — landmark güveni koptu |

Sayılmayan hareketler **atılmaz, loglanır.** "Yarım tekrar" bilgisi hem kullanıcıya geri
bildirim hem de analytics için değerlidir.

---

## 4. Kalibrasyon Bağlantısı

Eşikler mutlak yazılmaz. İki tür eşik vardır:

```
absolute:  180 derece gibi fiziksel sınırlar      → sabit yazılabilir
relative:  kişisel ROM'un yüzdesi                → cal_ref ile tanımlanır
```

Spec'te göreli eşik şu şekilde yazılır:

```
threshold:
  type: relative
  cal_ref: elbow_angle_min        # kalibrasyonda ölçülen kişisel değer
  factor: 0.85                    # bunun %85'ine ulaşmalı
```

Kalibrasyon protokolü: kullanıcıdan **3 kontrollü tekrar** istenir, aralarındaki medyan alınır
(ortalama değil — tek kötü tekrar kalibrasyonu bozmasın). Zamanla güncellenir.

---

## 5. Hata Tanımı Formatı

```
id: INSUFFICIENT_DEPTH
severity: form | safety
phase: TOP | DESCENDING | BOTTOM | ASCENDING | REP_END
condition: <feature koşulu — göreli eşikle>
priority: 1..5              # düşük sayı = önce söylenir
cooldown_s: 4.0
view_required: SIDE | FRONT | ANY
feedback_tr: "Biraz daha aşağı in."
feedback_en: "Go a little lower."
```

Kurallar:
- `severity: safety` olan hatalar cooldown'ı **bypass eder** ve her zaman önceliklidir
- `phase: REP_END` olan hatalar rep tamamlandığında değerlendirilir (canlı değil)
- `view_required` sağlanmıyorsa hata **hiç değerlendirilmez** — tahmin edilmez
- Feedback metni **kısa ve eyleme dönük** olmalı: "kalçan çok yüksek" değil,
  "kalçanı indir". Kullanıcı hareket halindeyken teşhis değil, komut duymak ister.

### Feedback öncelik ve cooldown politikası

Ortak, spec'ten bağımsız:

```
safety > form > motivation
aynı hata için         : min 4.0 s
herhangi bir cue için  : min 2.5 s
rep başına             : en fazla 1 cue
TTS politikası         : QUEUE_FLUSH — geçerliliğini yitirmiş cue kesilir
```

Geç gelen "aşağı in" uyarısı, hiç uyarı vermemekten daha zararlıdır.

---

## 6. `ml_candidates` Bölümü — Neden Var

Her spec, **rule engine'in ayırt edemediği** hata sınıflarını listelemek zorundadır:

```
ml_candidates:
  - id: LOSS_OF_CONTROL
    why_rules_fail: "Tek bir feature eşiği değil; hız + sapma + asimetrinin zaman içindeki
                     ortak paterni. Eşikle yazıldığında ya çok hassas ya çok kör oluyor."
    needed_features: [velocity_profile, angle_variance, side_asymmetry]
```

Bu liste Phase 8'de ML'e geçişin **gerekçe belgesidir**. "ML ekleyelim" demek yerine
"şu 4 hatayı kuralla ayırt edemiyoruz" diyebilmek gerekir.

---

## 7. Yeni Egzersiz Ekleme Kontrol Listesi

1. `references/template.md` kopyala → `docs/computer-vision/<exercise>.md`
2. `required_view` belirle — hangi açıdan güvenilir ölçülüyor?
3. `raw_signal` seç — hareketi en iyi temsil eden **tek** açı hangisi?
4. Feature listesini `docs/computer-vision/feature-spec.md`'den seç.
   Yeni feature gerekiyorsa **önce** oraya ekle (`cv-engineer`)
5. Kalibrasyonda ne ölçüleceğini tanımla
6. Hataları yaz — her biri için hangi fazda değerlendirileceğini belirt
7. Eşiklere **başlangıç değeri** ver, "kalibre edilecek" olarak işaretle
8. `ml_candidates` bölümünü doldur (boş bırakma — boşsa neden boş olduğunu yaz)
9. Motor kodunda değişiklik gerekiyor mu? **Gerekiyorsa dur** — format eksik demektir
