# ADR 0004 — Hip-Centered Origin + Torso-Length Scaling

**Durum:** Kabul · Phase 0

## Bağlam

Kullanıcılar farklı boylarda, farklı vücut oranlarında ve kameraya farklı uzaklıklarda olacak.
Telefon farklı çözünürlüklerde farklı cihazlara kurulacak. Ham piksel koordinatlarına dayanan
hiçbir eşik bu koşullar arasında taşınamaz.

## Karar

Üç aşamalı, sırası bağlayıcı normalizasyon:

1. **Cihaz bağımsızlığı:** `x/image_height`, `y/image_height` (genişlikle değil yükseklikle böl —
   en-boy oranı korunsun)
2. **Smoothing:** One-Euro filter, normalizasyondan **önce**
3. **Vücut-göreli koordinat:** origin `mid_hip`, ölçek `distance(mid_shoulder, mid_hip)`

Geçerlilik kapısı: `torso_length < 0.05` ise tüm normalize feature'lar `null`.

Detaylar ve test vektörleri: `.claude/skills/pose-math/`

## Gerekçe

**Torso uzunluğu, harekete en az bağımlı vücut ölçüsüdür.** Push-up'ta bile omuz-kalça
mesafesi neredeyse sabit kalır. Squat'ta gövde eğilse de uzunluğu değişmez.

**Smoothing önce yapılır** çünkü normalizasyon çapası (kalça ve omuz) de gürültülüdür.
Çapa titrerse bu titreme normalize edilmiş *tüm* feature'lara yayılır — gürültü tek bir
landmark'tan tüm sisteme bulaşır.

**Açılar zaten ölçek ve öteleme değişmezdir**, yani normalizasyon esasen mesafe ve koordinat
feature'ları için gerekir. Yine de tutarlılık için tüm hesaplar normalize koordinatta yapılır.

## Sonuçlar

- Tüm eşikler "torso birimi" cinsinden yazılır; piksel eşiği yasaktır
- `torso_length` her frame'de hesaplanır ve setup validator tarafından mesafe kontrolünde
  de kullanılır
- Kalça veya omuz landmark'ları güvensizse **hiçbir** normalize feature üretilemez —
  bu, tek bir kayıp landmark'ın tüm frame'i geçersiz kılabileceği anlamına gelir; kabul edilmiştir
- Test vektörü olarak "aynı iskelet 2× büyütülüp ötelendiğinde tüm normalize değerler
  aynı kalmalı" kontrolü zorunludur — normalizasyonun doğruluğunun tek objektif kanıtı budur

## Reddedilen Alternatifler

**Shoulder width scaling.**
Reddedildi: yan görüşte iki omuz üst üste biner (foreshortening), omuz genişliği sıfıra
yaklaşır ve ölçek çöker. Push-up ve squat'ın birincil görüşü yan olduğu için bu ölçüt
tam olarak en çok ihtiyaç duyulduğu yerde başarısız oluyor.

**Person bounding-box normalization.**
Reddedildi: kutu boyutu uzuv pozisyonuna bağlı. Aynı kişi kolunu açtığında ölçek değişir,
yani ölçek hareketle birlikte oynar — normalizasyonun tam tersi.

**Ham piksel koordinatları.**
Reddedildi: cihaz, çözünürlük, mesafe ve kullanıcı boyuna bağımlı. Hiçbir eşik taşınamaz.

**Torso axis rotation alignment (gövdeyi dikeye döndürmek).**
Şimdilik uygulanmıyor: kural motoru için gerekmiyor ve yerçekimi yönü bilgisini yok ediyor —
oysa `hip_vertical_offset` gibi feature'lar tam olarak yerçekimi yönüne dayanıyor.
ML feature'ları için Phase 8'de opsiyonel olarak yeniden değerlendirilecek.
