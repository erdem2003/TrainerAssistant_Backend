# Squat Spec

> Format: `.claude/skills/exercise-spec/` · Feature tanımları: `feature-spec.md`
> Tüm eşikler `tuning_status: initial` — gerçek kullanıcı verisiyle henüz doğrulanmadı.

---

## meta

```yaml
id: SQUAT
name_tr: Squat
name_en: Squat
category: lower_body
type: rep_based
status: draft
```

## setup

```yaml
required_view: SIDE           # derinlik ve gövde açısı için
optional_view: FRONT          # valgus ve asimetri için

checks:
  - id: FULL_BODY_VISIBLE
    landmarks: [SHOULDER, HIP, KNEE, ANKLE, HEEL, FOOT_INDEX]
    min_confidence: 0.6

  - id: CORRECT_ANGLE
    condition: shoulder_width_ratio < 0.35        # SIDE modu
    tuning_status: initial

  - id: CORRECT_DISTANCE
    condition: 0.10 <= torso_length <= 0.30       # ayakta duruş, push-up'tan daha uzak
    tuning_status: initial

  - id: IN_POSITION
    condition: knee_angle > 150                   # ayakta başlıyor
    tuning_status: initial

  - id: CAMERA_STABLE
    condition: camera_drift < 0.05
    tuning_status: initial

setup_feedback_tr:
  CORRECT_ANGLE:    "Telefonu yan tarafına koy, seni profilden görmeli."
  CORRECT_DISTANCE: "Biraz geri git, tüm vücudun görünsün."
  IN_POSITION:      "Ayakta dik dur, başlayacağız."
  CAMERA_STABLE:    "Telefon sallanıyor, sabit bir yere koy."
```

> **Kamera yüksekliği notu:** squat derinliği `hip_above_knee` ile ölçülüyor ve bu ölçüm
> kameranın yüksekliğine duyarlı (perspektif). Telefon **diz-kalça hizasında** olmalı.
> Bu bir setup talimatı olarak kullanıcıya söylenir; otomatik tespiti Phase 3'te
> `hip`/`knee` görünür y-oranından denenecek — `open_questions`.

## features

```yaml
features:
  - name: knee_angle            role: phase_signal      view_dependent: false
  - name: hip_above_knee        role: error_detection   view_dependent: true   # SIDE
  - name: torso_angle_vertical  role: error_detection   view_dependent: true   # SIDE
  - name: hip_angle             role: error_detection   view_dependent: false
  - name: hip_velocity_y        role: error_detection   view_dependent: false
  - name: heel_lift             role: error_detection   view_dependent: true   # SIDE, düşük güven
  - name: knee_valgus           role: error_detection   view_dependent: true   # FRONT
  - name: side_asymmetry        role: error_detection   view_dependent: true   # FRONT
  - name: shoulder_width_ratio  role: setup             view_dependent: false
  - name: camera_drift          role: setup             view_dependent: false
  - name: torso_length          role: telemetry         view_dependent: false
```

## phase_signal

```yaml
raw_signal: knee_angle
direction: decreasing
p_max_cal: knee_angle_standing    # kişisel ayakta duruş açısı
p_min_cal: knee_angle_bottom      # kişisel en derin nokta
```

`p = clamp((knee_angle - p_min_cal) / (p_max_cal - p_min_cal), 0, 1)`

> **Neden `knee_angle` faz sinyali ama `hip_above_knee` derinlik ölçütü:**
> Faz sinyalinin görüntü perspektifine karşı dayanıklı olması gerekir — `knee_angle`
> bir açıdır, ölçek değişmezdir ve gürültüye toleranslıdır. Derinlik ise mutlak bir
> anatomik referans ister (kalça dizin üstünde mi altında mı) ve bunu açı veremez:
> uzun femurlu bir kullanıcı aynı diz açısında farklı derinliğe iner.
> İkisi farklı işler yapıyor, bu ayrım kasıtlıdır.

## rep_fsm

```yaml
thresholds:
  enter_descend: 0.85
  exit_top:      0.90
  enter_bottom:  0.35            # push-up'tan biraz yüksek
  exit_bottom:   0.45

gates:
  min_duration_s: 0.5            # squat push-up'tan yavaştır
  max_duration_s: 12.0
  min_rom:        0.50
  signal_gap_ms:  200

tuning_status: initial
```

> `enter_bottom` push-up'a göre yüksek (0.35 vs 0.30): squat'ta kalibrasyon sırasında
> kullanıcı genelde maksimumdan daha derine iner (ısınmış olur), bu da `p_min_cal`'ı
> aşağı çeker ve normal setlerde alt eşiğe ulaşmayı zorlaştırır.

## calibration

```yaml
protocol: "3 kontrollü squat. Talimat: 'Rahatça inebildiğin kadar in, sonra tam ayağa kalk.'"
aggregation: median
measures:
  - name: knee_angle_standing
    from: knee_angle'ın TOP fazındaki medyanı
    used_by: [INCOMPLETE_EXTENSION, phase_signal]
  - name: knee_angle_bottom
    from: knee_angle'ın rep içi minimumunun medyanı
    used_by: [phase_signal]
  - name: hip_above_knee_bottom
    from: hip_above_knee'nin rep içi minimumunun medyanı
    used_by: [INSUFFICIENT_DEPTH]
  - name: neutral_torso_angle
    from: torso_angle_vertical'in TOP fazındaki medyanı
    used_by: [EXCESSIVE_FORWARD_LEAN]
revalidate_after: 10 antrenman
```

> **Derinlik hedefi kalibrasyona bağlanıyor, mutlak "parallel"e değil.** Sebep: ayak
> bileği esnekliği ve femur uzunluğu kişiden kişiye çok değişir; herkesten parallel altı
> squat beklemek hem gerçekçi değil hem sakatlık riski. Sistem kişinin *kendi* güvenli
> derinliğini hedefler ve zamanla yeniden ölçer.

## errors

```yaml
errors:
  - id: INSUFFICIENT_DEPTH
    severity: form
    phase: BOTTOM
    view_required: SIDE
    condition:
      feature: hip_above_knee
      op: gt
      threshold: {type: relative, cal_ref: hip_above_knee_bottom, offset: +0.15}
      tuning_status: initial
    priority: 2
    cooldown_s: 4.0
    feedback_tr: "Biraz daha aşağı in."
    feedback_en: "Go a little deeper."

  - id: EXCESSIVE_FORWARD_LEAN
    severity: safety                        # bel için risk
    phase: DESCENDING
    view_required: SIDE
    condition:
      feature: torso_angle_vertical
      op: gt
      threshold: {type: relative, cal_ref: neutral_torso_angle, offset: +45}
      tuning_status: initial
    priority: 1
    cooldown_s: 4.0
    feedback_tr: "Göğsünü yukarı kaldır, çok öne eğiliyorsun."
    feedback_en: "Chest up, you're leaning too far forward."

  - id: KNEE_VALGUS
    severity: safety                        # diz için risk
    phase: ASCENDING                        # yukarı çıkarken belirginleşir
    view_required: FRONT
    condition:
      feature: knee_valgus
      op: lt
      threshold: {type: absolute, value: -0.15}
      tuning_status: initial
    priority: 1
    cooldown_s: 5.0
    feedback_tr: "Dizlerini dışa doğru it."
    feedback_en: "Push your knees outward."

  - id: HEEL_LIFT
    severity: form
    phase: BOTTOM
    view_required: SIDE
    condition:
      feature: heel_lift
      op: gt
      threshold: {type: absolute, value: 0.06}     # geniş eşik — landmark güveni düşük
      tuning_status: initial
    priority: 4
    cooldown_s: 8.0
    feedback_tr: "Topuklarını yere bastır."
    feedback_en: "Keep your heels on the ground."

  - id: INCOMPLETE_EXTENSION
    severity: form
    phase: REP_END
    view_required: ANY
    condition:
      feature: knee_angle                    # rep içi maksimum
      op: lt
      threshold: {type: relative, cal_ref: knee_angle_standing, factor: 0.93}
      tuning_status: initial
    priority: 4
    cooldown_s: 6.0
    feedback_tr: "Yukarıda tam ayağa kalk."
    feedback_en: "Stand up fully at the top."

  - id: ASYMMETRY
    severity: form
    phase: BOTTOM
    view_required: FRONT
    condition:
      feature: side_asymmetry
      op: gt
      threshold: {type: absolute, value: 12}       # derece
      tuning_status: initial
    priority: 3
    cooldown_s: 8.0
    feedback_tr: "Ağırlığını iki bacağına eşit ver."
    feedback_en: "Distribute your weight evenly."

  - id: TOO_FAST
    severity: form
    phase: REP_END
    view_required: ANY
    condition:
      feature: rep_eccentric_duration_s
      op: lt
      threshold: {type: absolute, value: 0.6}
      tuning_status: initial
    priority: 5
    cooldown_s: 8.0
    feedback_tr: "Daha kontrollü in."
    feedback_en: "Lower yourself more slowly."
```

## ml_candidates

```yaml
ml_candidates:
  - id: BUTT_WINK
    why_rules_fail: "Alt noktada pelvisin geriye dönmesi. ML Kit'te omurga landmark'ı yok;
                     kalça-omuz ilişkisinin ince değişiminden ancak dolaylı çıkarılabilir.
                     Kuralla ifade edilebilir tek bir geometrisi yok."
    needed_features: [hip_angle, torso_angle_vertical zaman serisi, alt nokta çevresi]
    priority_for_data_collection: medium

  - id: LOSS_OF_CONTROL
    why_rules_fail: "Kontrollü inmek ile 'çökmek' arasındaki fark hız profilinin şeklinde,
                     tek bir hız eşiğinde değil."
    needed_features: [hip_velocity_y profili, knee_angle varyansı]
    priority_for_data_collection: high

  - id: WEIGHT_SHIFT
    why_rules_fail: "Kullanıcı ağırlığı bir bacağa kaydırıyor ama diz açıları benzer kalabiliyor;
                     asimetri feature'ı bunu her zaman yakalamıyor. Kalça yanal kayması +
                     ayak basıncı paterni gerekiyor, ikincisi kameradan görünmüyor."
    needed_features: [mid_hip yanal konum, side_asymmetry, ayak landmark'ları]
    priority_for_data_collection: medium
```

## open_questions

- [ ] Kamera yüksekliği `hip_above_knee` ölçümünü ne kadar etkiliyor? Otomatik tespit
      mümkün mü, yoksa sadece setup talimatı mı kalacak? **Phase 3'te ölçülecek —
      bu, squat derinlik ölçümünün en büyük belirsizliği.**
- [ ] SIDE ve FRONT'un ikisi de değerli (derinlik vs valgus). Kullanıcıdan iki set mi
      isteyeceğiz, yoksa 45° bir kurulum ikisini birden kısmen mi verir? 45°'de her iki
      ölçüm de bozulur — muhtemelen hayır, ama ölçülmeli.
- [ ] `heel_lift` landmark güveni gerçekten yeterli mi? Değilse feature tamamen düşürülmeli;
      "bazen yanlış uyarı veren" bir kural, olmayan kuraldan kötüdür.
- [ ] Bodyweight squat ile ağırlıklı squat aynı spec mi? Ağırlık gövde açısını meşru
      şekilde değiştirir → `EXCESSIVE_FORWARD_LEAN` eşiği varyanta göre değişmeli.
