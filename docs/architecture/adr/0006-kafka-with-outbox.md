# ADR 0006 — Kafka + Outbox Pattern + Idempotent Consumer

**Durum:** Kabul · Phase 0 (uygulama Phase 11)

## Bağlam

Servisler arası iletişimin bir kısmı asenkron olacak (ADR 0005). Broker seçimi, hangi
olayların gerçekten event olduğu ve teslim garantilerinin nasıl sağlanacağı kararlaştırılmalı.

## Karar

**Broker: Kafka.** Yerel geliştirmede **Redpanda** (Kafka protokolü uyumlu, tek binary,
çok daha hafif; production'da gerçek Kafka'ya geçiş kod değişikliği gerektirmez).

**Outbox pattern zorunlu.** Event doğrudan publish edilmez; iş verisiyle **aynı transaction'da**
`outbox` tablosuna yazılır, ayrı bir relay süreci publish eder.

**Consumer'lar idempotent olmak zorunda.** Her event bir `event_id` taşır; consumer
işlenmiş id'leri tutar ve tekrarı sessizce yutar.

### Hangi olaylar event

| Olay | Karar | Gerekçe |
|---|---|---|
| `UserRegistered` | ✅ Event | Profil oluşturma, kayıt yanıtını bloklamamalı |
| `WorkoutCompleted` | ✅ Event | Ağır agregasyon kullanıcıyı bekletmemeli |
| `WorkoutAnalyzed` | ✅ Event | Analytics → Notification (Phase 11+) |
| `RepCompleted` | ❌ | Saniyede birkaç kez üretilir, tek başına anlamsız. Cihazda toplanır, `WorkoutCompleted` payload'ında toplu gider |
| `FormErrorDetected` | ❌ | Tamamen on-device, gerçek zamanlı sinyal. Backend'in anlık haberdar olmasının hiçbir kullanımı yok |
| `WorkoutStarted` / `ExerciseStarted` | ❌ | Offline-first mimaride oturum bitmeden backend'e bir şey gitmez |

## Gerekçe

**Kafka neden:** `analytics-service` gerçek bir stream consumer. Ayrıca event log replay
yeteneği somut fayda sağlıyor — analytics veritabanını sıfırlayıp tüm geçmişi yeniden
işleyebilmek, agregasyon mantığı değiştiğinde tek çözüm. Bu, RabbitMQ'nun kutudan
vermediği bir yetenek.

**Outbox neden:** "Veritabanı commit oldu ama event publish edilemedi" (veya tersi)
tutarsızlığı, iki farklı sisteme yazan her serviste kaçınılmazdır. Outbox bunu tek bir
transaction'a indirger. Bu, dağıtık sistemlerin en yaygın sessiz veri kaybı kaynağıdır.

**Idempotency neden:** Kafka **at-least-once** teslim verir. Exactly-once beklemek yanlıştır;
doğru cevap consumer'ı tekrara dayanıklı yapmaktır.

**Over-eventing'den kaçınma:** Bir olayın "gerçekleşiyor olması" onu event yapmaz.
Event, **başka bir bounded context'in tepki vermesi gereken** bir olgudur. `RepCompleted`
için backend'de tepki verecek kimse yok — broker'a rep başına mesaj göndermek maliyet
üretip fayda üretmez.

## Sonuçlar

- Her event şeması versiyonlanır; geriye uyumsuz değişiklik yeni event tipi gerektirir
- Event'ler `correlation_id` taşır — trace zinciri broker'da kopmamalı (Phase 12)
- Consumer lag ve outbox gecikmesi izlenen metriklerdir
- Yerel geliştirme Redpanda ile hafif kalır; Compose dosyası ağırlaşmaz
- Analytics'in yeniden hesaplanabilirliği bir özellik olarak korunur (retention politikası
  buna göre seçilir)

## Reddedilen Alternatifler

**RabbitMQ.**
Reddedildi: task queue ve RPC senaryolarında daha uygun, ama bizim ihtiyacımız o değil.
Replay yeteneği yok — analytics'i yeniden hesaplama gereksinimini karşılamıyor.

**Broker yok, senkron HTTP çağrıları.**
Reddedildi: analytics'in ağır agregasyonu workout ingest yanıtını bekletir; ayrıca analytics
düştüğünde antrenman kaydı da başarısız olur. Gereksiz coupling.

**Outbox yerine doğrudan publish.**
Reddedildi: DB commit ile publish arasındaki her hata sessiz veri kaybı üretir. Analytics'te
eksik antrenman, kullanıcının "ben bunu yapmıştım" dediği ve kimsenin açıklayamadığı
hata sınıfına dönüşür.

**Exactly-once semantiği hedeflemek.**
Reddedildi: Kafka transaction'larıyla mümkün ama karmaşıklığı yüksek ve consumer tarafında
yine idempotency gerekiyor. Idempotent consumer daha basit ve daha sağlam.
