# ADR 0002 — Tüm Gerçek Zamanlı Analiz On-Device

**Durum:** Kabul · Phase 0

## Bağlam

Pose detection ve form analizi cihazda ya da backend'de yapılabilir. Backend'de yapmak
daha güçlü modeller ve merkezi güncelleme imkanı sunar; cihazda yapmak gecikme ve
gizlilik avantajı verir.

## Karar

**Pose detection, feature extraction, rule engine, rep sayma, ML inference ve feedback
üretimi tamamen cihazda çalışır. Kamera görüntüsü hiçbir koşulda cihazdan çıkmaz.**

Backend'e yalnızca sayısal sonuçlar gider: antrenman özeti, rep metrikleri, tespit edilen
hatalar, skorlar. Opsiyonel ve açık onayla: landmark koordinat sekansları.

## Gerekçe

**1. Gecikme bütçesi kapatıyor.**
Sesli koçluk yararlı olması için hareketin içinde verilmelidir. On-device ~30 ms;
ağ üzerinden 200-1000 ms. Kullanıcı yukarı çıkarken "aşağı in" duyarsa uygulamaya
güvenini kaybeder. Geç bilgi, yanlış bilgidir.

**2. Offline çalışmak zorunda.**
Spor salonlarında ve bodrum katlarında internet çoğu zaman yoktur. Ağ bağımlılığı,
uygulamanın kullanılacağı yerin yarısında çalışmaması demektir.

**3. Gizlilik.**
Kullanıcının evinde spor yaparken çekilen video, taşınabilecek en hassas veri türlerinden
biridir. Sunucuya göndermek KVKK/GDPR yükü, saklama sorumluluğu ve ciddi itibar riski yaratır.
Göndermemek bu risk sınıfını tamamen ortadan kaldırır.

**4. Maliyet.**
Sunucu tarafı video/frame işleme kullanıcı başına sürekli GPU ve bant genişliği demektir.
Öğrenci projesi bütçesiyle uyumsuz; ücretsiz bir uygulama için sürdürülemez.

## Sonuçlar

- Frame bütçesi bağlayıcı bir kısıt haline gelir: 15 FPS analiz, frame başına 66 ms
- Model boyutu ve inference süresi birinci sınıf kısıt olur → küçük model tercihi (ADR 0003)
- Model güncellemesi uygulama güncellemesi gerektirir (veya sonradan model indirme mekanizması)
- Backend basitleşir: video işleme, object storage, GPU altyapısı gerekmez
- `android-realtime-cv` skill'inde "frame diske/loga/ağa yazılmaz" kuralı mutlaktır —
  geçici debug istisnası dahil

## Reddedilen Alternatifler

**Backend'de analiz.**
Reddedildi: gecikme, offline, gizlilik ve maliyet — dördü de aynı yöne işaret ediyor.

**Hibrit: cihazda rep sayma, backend'de form analizi.**
Reddedildi: form geri bildirimi de gerçek zamanlı olmak zorunda. Rep'i cihazda sayıp
formu 500 ms sonra söylemek, kullanıcı bir sonraki tekrarın ortasındayken uyarı vermek demektir.
Ayrıca hâlâ landmark akışını sürekli göndermek gerekir — bant genişliği ve pil maliyeti kalır.

**Antrenman sonrası backend analizi (batch).**
Reddedildi: gerçek zamanlı koçluk ürünün ana değer önerisi. Sonradan rapor vermek
farklı (ve daha zayıf) bir üründür. Not: ileride *ek* bir özellik olarak düşünülebilir,
ama gerçek zamanlı analizin yerine geçemez.
