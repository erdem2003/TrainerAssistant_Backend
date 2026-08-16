# Push-Up Spec

> Format: `.claude/skills/exercise-spec/` · Feature tanımları: `feature-spec.md`
> Tüm eşikler `tuning_status: initial` — gerçek kullanıcı verisiyle henüz doğrulanmadı.

---

## meta

```yaml
id: PUSH_UP
name_tr: Şınav
name_en: Push-Up
category: upper_body
type: rep_based
status: draft
```

## setup

```yaml
required_view: SIDE
optional_view: FRONT          # elbow_flare tespiti için ikincil mod

checks:
  - id: FULL_BODY_VISIBLE
    landmarks: [SHOULDER, ELBOW, WRIST, HIP, KNEE, ANKLE]
    min_confidence: 0.6

  - id: CORRECT_ANGLE
    condition: shoulder_width_ratio < 0.35        # yan görüş
    tuning_status: initial

  - id: CORRECT_DISTANCE
    condition: 0.12 <= torso_length <= 0.45       # image-height oranı
    tuning_status: initial

  - id: IN_POSITION
    condition: torso_inclination < 35             # gövde yataya yakın
    tuning_status: initial

  - id: CAMERA_STABLE
    condition: camera_drift < 0.05                # norm/s, 2 saniyelik pencerede
    tuning_status: initial

setup_feedback_tr:
  CORRECT_ANGLE:    "Telefonu yan tarafına koy, seni profilden görmeli."
  CORRECT_DISTANCE: "Telefonu biraz uzaklaştır, tüm vücudun görünsün."
  IN_POSITION:      "Şınav pozisyonuna geç."
  CAMERA_STABLE:    "Telefon sallanıyor, sabit bir yere koy."
```

## features

```yaml
features:
  - name: elbow_angle           role: phase_signal      view_dependent: false
  - name: hip_vertical_offset   role: error_detection   view_dependent: true   # SIDE
  - name: torso_inclination     role: setup             view_dependent: true   # SIDE
  - name: shoulder_velocity_y   role: error_detection   view_dependent: false
  - name: wrist_shoulder_offset role: setup             view_dependent: true   # SIDE
  - name: elbow_flare           role: error_detection   view_dependent: true   # FRONT
  - name: shoulder_width_ratio  role: setup             view_dependent: false
  - name: camera_drift          role: setup             view_dependent: false
  - name: torso_length          role: telemetry         view_dependent: false
```

## phase_signal

```yaml
raw_signal: elbow_angle
direction: decreasing            # aşağı inerken dirsek açısı azalır
p_max_cal: elbow_angle_top       # kişisel kilitleme açısı (kalibrasyon)
p_min_cal: elbow_angle_bottom    # kişisel en derin nokta (kalibrasyon)
```

`p = clamp((elbow_angle - p_min_cal) / (p_max_cal - p_min_cal), 0, 1)`

> Neden `elbow_angle`: hareketin tamamını tek boyutta temsil eden en temiz sinyal.
> Omuz yüksekliği alternatifti ama kameranın küçük açı sapmalarına çok daha duyarlı.

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

tuning_status: initial
```

## calibration

```yaml
protocol: "3 kontrollü şınav. Talimat: 'Yapabildiğin kadar aşağı in ve tam yukarı çık.'"
aggregation: median
measures:
  - name: elbow_angle_top
    from: elbow_angle'ın rep başındaki (TOP) medyan değeri
    used_by: [PARTIAL_LOCKOUT, phase_signal]
  - name: elbow_angle_bottom
    from: elbow_angle'ın rep içi minimumunun medyanı
    used_by: [INSUFFICIENT_DEPTH, phase_signal]
  - name: neutral_hip_offset
    from: hip_vertical_offset'in TOP fazındaki medyanı
    used_by: [HIP_SAG, HIP_PIKE]
revalidate_after: 10 antrenman
```

> `neutral_hip_offset` neden ölçülüyor: hiç kimsenin gövdesi geometrik olarak tam düz
> değildir ve kamera açısının küçük sapması sistematik bir kayma yaratır. Sapma, sıfırdan
> değil kişinin **kendi nötr duruşundan** ölçülür.

## errors

```yaml
errors:
  - id: INSUFFICIENT_DEPTH
    severity: form
    phase: BOTTOM
    view_required: ANY
    condition:
      feature: elbow_angle
      op: gt
      threshold: {type: relative, cal_ref: elbow_angle_bottom, factor: 1.15}
      tuning_status: initial
    priority: 2
    cooldown_s: 4.0
    feedback_tr: "Biraz daha aşağı in."
    feedback_en: "Go a little lower."

  - id: HIP_SAG
    severity: safety                       # bel için risk
    phase: DESCENDING
    view_required: SIDE
    condition:
      feature: hip_vertical_offset
      op: gt
      threshold: {type: relative, cal_ref: neutral_hip_offset, offset: +0.12}
      tuning_status: initial
    priority: 1
    cooldown_s: 4.0
    feedback_tr: "Kalçanı yukarı al, karnını sık."
    feedback_en: "Lift your hips, tighten your core."

  - id: HIP_PIKE
    severity: form
    phase: DESCENDING
    view_required: SIDE
    condition:
      feature: hip_vertical_offset
      op: lt
      threshold: {type: relative, cal_ref: neutral_hip_offset, offset: -0.12}
      tuning_status: initial
    priority: 3
    cooldown_s: 4.0
    feedback_tr: "Kalçanı biraz indir, vücudun düz olsun."
    feedback_en: "Lower your hips, keep your body straight."

  - id: PARTIAL_LOCKOUT
    severity: form
    phase: REP_END
    view_required: ANY
    condition:
      feature: elbow_angle           # rep içi maksimum
      op: lt
      threshold: {type: relative, cal_ref: elbow_angle_top, factor: 0.92}
      tuning_status: initial
    priority: 4
    cooldown_s: 6.0
    feedback_tr: "Yukarıda kollarını tam aç."
    feedback_en: "Fully extend your arms at the top."

  - id: ELBOW_FLARE
    severity: safety                       # omuz için risk
    phase: BOTTOM
    view_required: FRONT
    condition:
      feature: elbow_flare
      op: gt
      threshold: {type: absolute, value: 0.55}
      tuning_status: initial
    priority: 1
    cooldown_s: 5.0
    feedback_tr: "Dirseklerini vücuduna yaklaştır."
    feedback_en: "Keep your elbows closer to your body."

  - id: TOO_FAST
    severity: form
    phase: REP_END
    view_required: ANY
    condition:
      feature: rep_eccentric_duration_s      # rep-level aggregate
      op: lt
      threshold: {type: absolute, value: 0.5}
      tuning_status: initial
    priority: 5
    cooldown_s: 8.0
    feedback_tr: "Daha kontrollü in."
    feedback_en: "Lower yourself more slowly."
```

### Öncelik notu

`HIP_SAG` ve `ELBOW_FLARE` `severity: safety` — cooldown'ı bypass eder ve her zaman
önce söylenir. Sebep: ikisi de bel ve omuz için gerçek yaralanma riski taşıyor,
`INSUFFICIENT_DEPTH` ise sadece verimsizlik.

## ml_candidates

```yaml
ml_candidates:
  - id: LOSS_OF_CONTROL
    why_rules_fail: "Aşağı inerken kontrolü bırakıp 'düşmek' ile kontrollü inmek arasındaki
                     fark tek bir hız eşiğiyle ayrılmıyor — hız profilinin şekli önemli.
                     Sabit eşik hızlı ama kontrollü kullanıcıyı yanlış uyarıyor."
    needed_features: [shoulder_velocity_y profili, elbow_angle varyansı]
    priority_for_data_collection: high

  - id: SCAPULAR_INSTABILITY
    why_rules_fail: "Omuz kürek stabilitesi ML Kit landmark'larıyla doğrudan ölçülemiyor;
                     ancak omuz-dirsek-gövde ilişkisinin zaman içindeki paterninden dolaylı
                     çıkarılabilir. Kuralla ifade edilebilir bir geometrisi yok."
    needed_features: [çoklu eklem açısı zaman serisi]
    priority_for_data_collection: medium

  - id: HEAD_DROP
    why_rules_fail: "Landmark mevcut (NOSE) ama yan görüşte güveni düşük ve boyun açısı
                     kişiden kişiye çok değişiyor. Sabit eşik çalışmıyor."
    needed_features: [nose, ear, shoulder ilişkisi]
    priority_for_data_collection: low
```

## open_questions

- [ ] `enter_bottom = 0.30` eşiği, kalibrasyonu zorlanarak yapan bir kullanıcıda çok mu katı?
      Phase 3'te gerçek kayıtla ölçülecek.
- [ ] Diz üstü (kolay) şınav ayrı bir egzersiz mi, yoksa aynı spec'in bir varyantı mı?
      `torso_inclination` ve `hip_vertical_offset` eşikleri farklı olmalı.
- [ ] FRONT görüş ikincil mod olarak destekleniyor ama `hip_vertical_offset` orada `null`.
      Kullanıcıya iki kurulumu da mı sunacağız, yoksa SIDE'ı mı zorunlu kılacağız?
