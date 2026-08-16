# `<Exercise Name>` Spec

> Şablon. Kopyala → `docs/computer-vision/<exercise>.md`.
> `<...>` yerlerini doldur, doldurulmayan bölüm bırakma — gerekmiyorsa "N/A + sebep" yaz.

---

## meta

```yaml
id: <EXERCISE_ID>              # UPPER_SNAKE, dataset'te bu değer kullanılır
name_tr: <Türkçe ad>
name_en: <English name>
category: <upper_body | lower_body | core | full_body>
type: rep_based                # rep_based | hold_based
status: draft                  # draft | calibrating | stable
```

## setup

Bu koşullar sağlanmadan **rep sayılmaz**, hata değerlendirilmez.

```yaml
required_view: <SIDE | FRONT>
optional_view: <... | none>    # ikincil modda desteklenen görüş

checks:
  - id: FULL_BODY_VISIBLE
    landmarks: [<gerekli landmark listesi>]
    min_confidence: 0.6
  - id: CORRECT_ANGLE
    condition: <görüş açısını doğrulayan geometrik koşul>
  - id: CORRECT_DISTANCE
    condition: <torso_length bandı>
  - id: CAMERA_STABLE
    condition: <ardışık frame'lerde global kayma eşiği>

setup_feedback_tr: "<kullanıcıya kurulum talimatı>"
setup_feedback_en: "<setup instruction>"
```

## features

`docs/computer-vision/feature-spec.md` içinde tanımlı feature'lardan seçilir.
Burada yeni feature **tanımlanmaz**, sadece referans verilir.

```yaml
features:
  - name: <feature_name>
    role: <phase_signal | error_detection | setup | telemetry>
    view_dependent: <true | false>
```

## phase_signal

```yaml
raw_signal: <feature_name>
direction: <decreasing | increasing>   # hareket alt noktaya giderken raw_signal azalıyor mu?
p_max_cal: <kalibrasyon referansı — p=1.0 karşılığı>
p_min_cal: <kalibrasyon referansı — p=0.0 karşılığı>
```

## rep_fsm

```yaml
thresholds:
  enter_descend: 0.85
  exit_top:      0.90
  enter_bottom:  0.30
  exit_bottom:   0.40

gates:
  min_duration_s: 0.4
  max_duration_s: 10.0
  min_rom:        0.55
  signal_gap_ms:  200

tuning_status: <initial | field_tested>   # initial = gerçek kullanıcı verisiyle henüz doğrulanmadı
```

## calibration

```yaml
protocol: <kullanıcıdan istenecek hareket — kaç tekrar, hangi talimatla>
aggregation: median            # tek kötü tekrar kalibrasyonu bozmasın
measures:
  - name: <cal_ref adı>
    from: <hangi feature'ın hangi istatistiği — ör. elbow_angle'ın rep içi minimumu>
    used_by: [<bu değere bağlı eşiklerin id'leri>]
revalidate_after: <kaç antrenman sonra yeniden ölçülür>
```

## errors

```yaml
errors:
  - id: <ERROR_ID>
    severity: <form | safety>
    phase: <TOP | DESCENDING | BOTTOM | ASCENDING | REP_END>
    view_required: <SIDE | FRONT | ANY>
    condition:
      feature: <feature_name>
      op: <lt | gt | outside_band>
      threshold:
        type: <relative | absolute>
        # type: relative — iki biçimden BİRİ:
        cal_ref: <kalibrasyon referansı>
        factor: <çarpan>       # çarpımsal: cal_ref * factor    (açı gibi oransal büyüklükler)
        offset: <+/- sapma>    # toplamsal: cal_ref + offset     (nötr duruştan sapma ölçen feature'lar)
        # type: absolute:
        value: <sabit değer>
      tuning_status: <initial | field_tested>
    priority: <1..5>
    cooldown_s: <saniye>
    feedback_tr: "<kısa, eyleme dönük komut>"
    feedback_en: "<short, actionable cue>"
```

## ml_candidates

Rule engine'in **ayırt edemediği** hatalar. Boş bırakma — boşsa sebebini yaz.

```yaml
ml_candidates:
  - id: <ERROR_ID>
    why_rules_fail: "<neden eşikle yazılamıyor — somut ol>"
    needed_features: [<gerekecek feature'lar>]
    priority_for_data_collection: <high | medium | low>
```

## open_questions

Bu spec'te henüz karara bağlanmamış noktalar. Boş olmalı — doluysa spec `stable` olamaz.

- [ ] `<soru>`
