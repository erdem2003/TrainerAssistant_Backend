# ADR 0005 — Microservice Sınırları ve Database-per-Service

**Durum:** Kabul · Phase 0 (uygulama Phase 10)

## Bağlam

Backend baştan dağıtık kurulacak. Bu bir teknik zorunluluk değil, bilinçli bir proje
hedefi: sistem aynı anda bitirme projesi, Play Store ürünü ve işveren vitrini olarak
hizmet edecek ve microservice yetkinliğinin gösterilmesi hedeflerden biri.

Teknik açıdan modular monolith bu ölçekte daha ucuz olurdu; bu trade-off tartışıldı ve
dağıtık mimari bilinçli olarak seçildi.

## Karar

**Beş bileşen:** `api-gateway`, `auth-service`, `user-service`, `workout-service`,
`analytics-service`. Her servisin kendi veritabanı vardır.

| Servis | Bounded Context | DB |
|---|---|---|
| `api-gateway` | Edge: routing, JWT doğrulama, rate limit, correlation ID | — |
| `auth-service` | Kimlik doğrulama: credential, token yaşam döngüsü, hesap devri | `auth_db` |
| `user-service` | Kullanıcı profili: ölçüler, kalibrasyon, tercihler | `user_db` |
| `workout-service` | Antrenman: oturum ingest, set/rep/hata kayıtları, egzersiz kataloğu | `workout_db` |
| `analytics-service` | Türetilmiş bilgi: trend, yorgunluk, rekor, agregasyon | `analytics_db` |

**Değişmez kurallar:**
- Hiçbir servis başka servisin veritabanına dokunmaz. İstisna yok.
- Servisler arası senkron çağrı minimumda; gereken veri event ile replike edilir.
- Her servis kendi migration'larını taşır.

## Gerekçe

**Sınırlar veriyle çizildi, işlevle değil.** Bir servis, kendi verisinin tek sahibiyse
servistir. `auth_db`'deki credential'a başka kimse dokunmaz; `workout_db`'deki rep kayıtlarına
analytics doğrudan erişmez, event ile kendi modelini kurar.

**auth ve user neden ayrı:** farklı hassasiyet sınıfları. Credential'lar en sıkı erişim
kontrolünü gerektirir; profil verisi çok daha sık okunur/yazılır. Ayrıca hesap silme
(Play Store zorunluluğu) bu ayrımla çok daha temiz uygulanır.

**analytics neden ayrı:** okuma ve yazma profili tamamen farklı. Ağır agregasyon sorguları
workout ingest yolunu yavaşlatmamalı. Bu, gerçek bir CQRS gerekçesidir.

## Sonuçlar

- Dağıtık sistemin bilinen maliyetleri kabul edilmiştir: eventual consistency, dağıtık
  hata ayıklama, servisler arası sözleşme yönetimi, daha karmaşık lokal geliştirme
- Correlation ID ve structured logging **Phase 10'dan itibaren zorunlu** — dağıtık sistemde
  bunlar olmadan hata ayıklama pratikte imkansız
- Docker Compose ile tek komutla ayağa kalkmalı; aksi halde geliştirme hızı çöker
- Servis sözleşmeleri (REST şemaları, event şemaları) `architect` sahipliğindedir

## Reddedilen Alternatifler

**Modular monolith → sonra split.**
Teknik olarak bu ölçekte daha ucuz olurdu ve ilk öneri buydu. Reddedildi: proje hedefleri
arasında dağıtık sistem yetkinliğinin gösterilmesi var ve "sonra bölerim" pratikte çoğu
zaman gerçekleşmiyor. Karar bilinçli, maliyeti bilinerek alındı.

**Ayrı `exercise-service`.**
Reddedildi: egzersiz tanımları neredeyse hiç değişmeyen, okuma-ağırlıklı statik veridir.
Ayrı servis + ayrı DB + network hop'u sıfır fayda üretip her workout sorgusuna gecikme ekler.
Egzersiz kataloğu `workout-service` içinde bir modül olarak durur; gerçekten bağımsız
değişmeye başlarsa ayrılır.

**Ayrı `recommendation-service` ve `notification-service` (MVP'de).**
Reddedildi: analytics verisi birikmeden önerilecek bir şey yok, kullanıcı yokken bildirilecek
bir şey yok. Phase 11+ için planlandı.

**`auth` ve `user`'ı birleştirmek.**
Reddedildi: hassasiyet sınıfları ve erişim profilleri farklı (yukarıda). Ayrıca bu, sistemde
en az bir gerçek servis-arası event akışı (`UserRegistered`) bulunmasını sağlıyor —
mimarinin doğru kurulduğunun kanıtı.
