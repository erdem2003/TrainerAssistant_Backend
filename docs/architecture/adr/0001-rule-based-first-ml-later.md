# ADR 0001 — Önce Rule-Based, Veri Biriktikçe ML

**Durum:** Kabul · Phase 0

## Bağlam

Pose landmark'larından form analizi iki şekilde yapılabilir: geometrik kurallarla
(açı eşikleri, state machine) veya eğitilmiş bir ML modeliyle. Projede henüz hiç veri yok
ve kullanıcılar farklı evlerde/salonlarda, farklı vücut oranlarıyla uygulamayı kullanacak.

## Karar

**Rule-based (geometrik) analiz ile başlanır. ML, ancak rule engine'in çözemediği
belgelenmiş hata sınıfları ve yeterli veri birikince eklenir (Phase 8).**

ML'e geçiş bir tarih değil, bir eşiktir:
- ≥ 15 farklı kullanıcı
- kullanıcı başına ≥ 40 rep
- her hata sınıfı için ≥ 150 pozitif örnek

## Gerekçe

**1. Rule engine, ML'in alternatifi değil önkoşuludur.**
Dataset'i label'lamak için rep segmentasyonuna ihtiyaç var. Rep sınırı olmadan 10.000 frame'i
elle etiketlemek pratikte imkansızdır. Rule engine ayrıca ön-etiketleme (weak supervision)
üreterek labeling maliyetini bir kat düşürür. Yani bu ikisi arasında "ya/ya da" seçimi
yapmak yanlış kurulmuş bir sorudur.

**2. Sesli koçluk açıklanabilirlik ister.**
"Incorrect" diyen bir sınıflandırıcı koç değildir. Sistemin *ne yanlış* olduğunu söylemesi
gerekir. Explainability burada opsiyonel bir güzellik değil, ürünün temel gereksinimidir.

**3. Veri yokken model olmaz.**
Sıfır veriyle başlanan bir ML projesi, ilk çalışan sürümünü aylar sonra üretir.
Rule engine ilk günden çalışır ve veri toplamayı besleyecek kullanıcıyı getirir.

**4. Kullanıcılar arası varyansın cevabı ML değil, kalibrasyondur.**
15 kişilik bir dataset'in öğrenebileceği vücut-oranı genellemesini, kişi başına 3 tekrarlık
bir kalibrasyon doğrudan ölçer. Daha ucuz ve daha güvenilir.

## Sonuçlar

- Phase 3-4'te push-up ve squat tamamen kuralla çalışır
- Her egzersiz spec'i `ml_candidates` bölümü tutmak zorundadır — bu liste, ML'e geçişin
  gerekçe belgesidir
- Rep sayma **kalıcı olarak** rule-based kalır, ML'e hiç geçmez (ADR 0003)
- Eşiklerin kalibrasyona göreli tanımlanması zorunlu hale gelir
- Dataset toplama pipeline'ı (Phase 6) rule engine'e bağımlıdır, tersi değil

## Reddedilen Alternatifler

**Tamamen ML-based (baştan itibaren).**
Reddedildi: veri yok, labeling aracı yok, açıklanabilirlik yok. Ayrıca hangi hataların
gerçekten oluştuğunu bilmeden label şeması tasarlanamaz — rule engine bu keşfi yapıyor.

**Tamamen rule-based (kalıcı).**
Reddedildi: hareket kalitesi, kontrol kaybı ve kompanzasyon paternleri tek bir eşikle
ifade edilemiyor. Bunlar için eşik yazma denemesi ya çok hassas ya çok kör sonuç veriyor.

**Hazır public dataset ile başlamak.**
Reddedildi: mevcut fitness pose dataset'leri farklı landmark şemaları, farklı kamera
kurulumları ve genelde sadece egzersiz sınıflandırma etiketleri içeriyor — form hatası
etiketi yok. Bizim ihtiyacımız olan etiket türü mevcut değil.
