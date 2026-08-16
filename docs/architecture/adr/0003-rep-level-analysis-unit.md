# ADR 0003 — ML Analiz Birimi Frame Değil, Rep

**Durum:** Kabul · Phase 0

## Bağlam

Egzersiz zamana bağlı bir harekettir; tek bir frame'e bakarak "bu şınav doğru" demek
yetersizdir. Bu gözlem doğal olarak sekans modellerine (LSTM, 1D CNN, Temporal CNN,
Transformer) işaret ediyor gibi görünür.

Ancak sistemde zaten bir rep state machine var ve hareketi tekrarlara segment ediyor.

## Karar

**ML modelinin analiz birimi bir rep'tir.** Rep tamamlandığında o rep boyunca toplanan
feature'ların aggregate'leri (min, max, ortalama, süre, varyans, hız profili özetleri)
çıkarılır ve tabular bir örnek oluşturur.

**Sekans modelleri (LSTM/TCN/Transformer) kullanılmaz.**

Gerçek zamanlı, frame-level geri bildirim ML'in değil **rule engine'in** işidir.

## Gerekçe

**1. Temporal problem, tabular probleme indirgeniyor.**
State machine segmentasyonu zaten zaman boyutunu çözüyor. Rep sınırları belliyse,
"bu rep'in en düşük dirsek açısı", "eccentric süresi", "kalça sapmasının maksimumu" gibi
aggregate'ler hareketin zamansal karakterini yeterince taşır. Modelin ayrıca zaman
modellemeyi öğrenmesine gerek kalmaz.

**2. Veri rejimi sekans modelini kaldırmıyor.**
15-30 kullanıcı ile bir LSTM eğitmek kaçınılmaz olarak overfit üretir. Rep-level tabular
veri ise aynı kullanıcı sayısıyla binlerce örnek verir ve ağaç tabanlı modeller bu rejimde
en güçlüsüdür.

**3. Frame bütçesi.**
On-device kısıt (ADR 0002) altında her frame'de sekans modeli koşturmak bütçeyi yer.
Rep-level model ~2 saniyede bir, bir kez çalışır — maliyeti ihmal edilebilir.

**4. Açıklanabilirlik.**
Feature importance doğrudan "hangi ölçüm bu kararı verdirdi" sorusunu cevaplar.
Sesli koçluk için gerekli olan tam da bu.

**5. İki zaman ölçeği doğal olarak ayrışıyor.**

| | Rule Engine | ML Model |
|---|---|---|
| Ne zaman | her frame (~15 Hz) | rep sonunda (~0.5 Hz) |
| Ne der | "biraz daha aşağı in" | "bu rep'te kontrolü kaybettin" |
| Bütçe | < 1 ms | < 5 ms |

## Sonuçlar

- Rep segmentasyonunun doğruluğu ML'in de doğruluğunu belirler → FSM kritik altyapı
- Dataset şeması rep-level tabular olur (ham landmark'lar yine saklanır, feature'lar
  sonradan yeniden türetilebilsin diye)
- Model seçimi küçük ve hızlı modellere kayar: LightGBM / küçük MLP
- Anlık geri bildirim tamamen rule engine'e bağımlı kalır — bu katman ihmal edilemez
- `PARTIAL_REP`'ler de loglanır; segmentasyona girmeyen hareket veri olarak kaybolmaz

## Reddedilen Alternatifler

**Frame-level classification.**
Reddedildi: tek frame hareketin fazını taşımıyor. Ayrıca ardışık frame'ler neredeyse
aynı olduğu için dataset'te devasa yapay korelasyon ve leakage riski yaratıyor.

**Sliding window classification (sabit pencere).**
Reddedildi: pencere boyutu tempo'ya bağlı. Hızlı bir kullanıcının 1.5 saniyelik rep'i ile
yavaş bir kullanıcının 4 saniyelik rep'i aynı pencereye sığmıyor. Rep sınırı doğal ve
adaptif bir penceredir; sabit pencere değildir.

**LSTM / Temporal CNN / Transformer.**
Reddedildi: veri ihtiyacı, model boyutu, inference maliyeti ve açıklanabilirlik kaybı —
hepsi bu problemde karşılığı olmayan bedeller. Rep aggregation aynı bilgiyi taşıyor.
Not: 30+ kullanıcı ve kalite skorunda gerçek bir tavan görülürse yeniden değerlendirilebilir;
o durumda bu ADR `Superseded` işaretlenir.

**Rep sayımını da ML'e vermek.**
Reddedildi: rep sayısı kullanıcının doğrudan gördüğü ve uygulamaya güvenini belirleyen
sayıdır. %97 doğru bir model burada %100 deterministik bir sayaçtan kötüdür.
