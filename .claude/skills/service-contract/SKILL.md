---
name: service-contract
description: Backend API ve event sözleşmelerinin tek doğruluk kaynağı — URL/sürümleme, hata biçimi, idempotency, sayfalama, JWT taşıma, outbox ve event şema kuralları. Bir endpoint yazılacaksa, bir event tanımlanacaksa veya servisler arası bir çağrı eklenecekse kullan.
---

# Servis Sözleşmesi — Tek Doğruluk Kaynağı

Beş servis ayrı ayrı yazılacak. Sözleşme kuralları tek yerde durmazsa her servis kendi
hata biçimini, kendi sayfalama parametresini ve kendi tarih formatını üretir — ve istemci
her servise ayrı ayrı uyum sağlamak zorunda kalır. Bu dosya onu engeller.

> Sınır kararları burada **değil**: hangi servisin ne verisine sahip olduğu ADR 0005'te,
> hangi olayın event olduğu ADR 0006'da. Burası "nasıl yazılır" sorusunun cevabı.

---

## 1. URL ve sürümleme

```
/v1/<kaynak>[/<id>][/<alt-kaynak>]
```

- Sürüm **yolda**, header'da değil. Tarayıcıdan ve curl'den test edilebilir olmalı.
- Kaynak adları **çoğul ve İngilizce**: `/v1/workouts`, `/v1/users/me`.
- Fiil yok. `/v1/workouts/sync` gibi bir yol, aslında eksik modellenmiş bir kaynağın işaretidir.
- Kırıcı değişiklik `/v2` açar. Alan **eklemek** kırıcı değildir; alan silmek veya anlamını
  değiştirmek kırıcıdır.

## 2. Kimlik

- `Authorization: Bearer <jwt>`
- Doğrulama **`api-gateway`'de** yapılır. Arka servisler doğrulanmış kimliği
  `X-User-Id` header'ından okur ve **kendileri tekrar doğrulamaz**.
- Gateway bu header'ı gelen istekten **her zaman siler**, sonra kendi yazar. Aksi hâlde
  istemci başka bir kullanıcının kimliğini uydurabilir.

## 3. Hata biçimi

Tek biçim, istisnasız:

```json
{
  "error": {
    "code": "WORKOUT_NOT_FOUND",
    "message": "Kayıt bulunamadı",
    "details": {"workout_id": "..."},
    "correlation_id": "01HQ..."
  }
}
```

- `code` **makine içindir**: `SCREAMING_SNAKE`, sabit, çevrilmez. İstemci buna göre dallanır.
- `message` insan içindir ve değişebilir. **İstemci mesaja göre karar vermez.**
- `correlation_id` her hatada döner — kullanıcı ekran görüntüsü gönderdiğinde log'da
  tek satırda bulunur.

| Durum | Kod | Ne zaman |
|---|---|---|
| 400 | doğrulama | Gövde şemaya uymuyor |
| 401 | kimlik yok/geçersiz | Token eksik veya süresi dolmuş |
| 403 | yetki yok | Token geçerli ama bu kaynağa erişemez |
| 404 | bulunamadı | Kaynak yok **ya da** başkasına ait (bilgi sızdırmamak için) |
| 409 | çakışma | Aynı doğal anahtar farklı içerikle geldi |
| 422 | işlenemez | Şema doğru, iş kuralı ihlal edildi |
| 429 | hız sınırı | Rate limit |

`404` seçimi bilinçli: başkasının kaynağına `403` dönmek, o kaynağın **var olduğunu**
doğrular. Var olmayanla başkasınınki ayırt edilemez olmalı.

## 4. Idempotency

Yazma uçlarında **istemci UUID üretir**. Mobil taraf bunu zaten yapıyor
(`WorkoutRecord.id`, ADR 0006'nın istemci tarafı).

```
POST /v1/workouts   { "id": "uuid", ... }

201  ilk yazım
200  aynı id daha önce yazıldı → mevcut kayıt döner, hata YOK
409  aynı id, FARKLI içerik → gerçek çakışma
```

Ağ hatasında tekrar denemek güvenli olmalı. `200` dönmek yerine `409` dönmek, offline-first
bir istemcide senkron kuyruğunu kilitler.

## 5. Sayfalama

Cursor tabanlı, offset değil:

```
GET /v1/workouts?limit=50&cursor=<opak>
→ { "items": [...], "next_cursor": "..." | null }
```

Offset sayfalama, araya yeni kayıt girdiğinde satır atlar veya tekrarlar. Antrenman
listesi tam olarak böyle bir liste — en yeni üstte ve sürekli ekleniyor.

`limit` varsayılan 50, tavan 200.

## 6. Tarih ve sayı

- Zaman damgaları **UTC epoch milisaniye** (`int`). Mobil taraf da böyle saklıyor.
  ISO-8601 string kullanılmaz: saat dilimi belirsizliği ve ayrıştırma farkı üretir.
- **Gün kavramı sunucuda hesaplanmaz.** "Bugün kaç tekrar" sorusunun cevabı kullanıcının
  saat dilimine bağlı; istemci kendi gün sınırını hesaplar ve aralık gönderir.
- Ondalık sayılar `float`; para yok, `decimal` gerekmiyor.
- Süreler **milisaniye** (`int`), saniye değil — mobil taraf da öyle saklıyor.

## 7. Alan adlandırma

- JSON'da `snake_case`. Python tarafıyla uyumlu, dönüşüm gerekmiyor.
- Mobil `camelCase` kullanıyor; dönüşüm **istemcide** yapılır. Sunucu Python'un doğal
  biçimini korur.
- Enum değerleri **`SCREAMING_SNAKE` ve isim olarak** taşınır, ordinal olarak değil.
  `HIP_SAG` gönderilir, `0` değil — enum sırası değişince ordinal sessizce kayar.

## 8. Event şeması

```json
{
  "event_id": "uuid",
  "event_type": "WorkoutCompleted",
  "occurred_at": 1786800000000,
  "correlation_id": "01HQ...",
  "payload": { }
}
```

- `event_id` **idempotency anahtarıdır.** Consumer işlenmiş id'leri tutar ve tekrarı
  sessizce yutar (Kafka at-least-once verir).
- Topic adı: `<bounded-context>.<olay>` → `workout.completed`
- Key seçimi: **aynı varlığın olayları aynı partition'a düşmeli.** Workout event'leri
  `user_id` ile key'lenir; böylece bir kullanıcının olayları sıralı işlenir.
- Payload **kendine yeter.** Consumer, üreten servise geri soru sormak zorunda kalmamalı —
  o senkron bağımlılık, event'in var olma sebebini ortadan kaldırır.

### Outbox

Event **doğrudan publish edilmez.** İş verisiyle aynı transaction'da `outbox` tablosuna
yazılır; ayrı bir relay publish eder.

```sql
CREATE TABLE outbox (
  id            UUID PRIMARY KEY,
  event_type    TEXT        NOT NULL,
  topic         TEXT        NOT NULL,
  partition_key TEXT        NOT NULL,
  payload       JSONB       NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at  TIMESTAMPTZ
);
CREATE INDEX ON outbox (created_at) WHERE published_at IS NULL;
```

Kısmi index bilinçli: relay yalnızca yayınlanmamış satırları tarar ve tablo büyüdükçe
sorgu maliyeti sabit kalır.

## 9. Sağlık uçları

Her servis:

- `GET /health/live` — süreç ayakta mı. Bağımlılık kontrol **etmez**.
- `GET /health/ready` — trafik alabilir mi. DB ve broker bağlantısını kontrol eder.

Ayrım önemli: `live` başarısızsa süreç yeniden başlatılır. DB geçici olarak düştüğünde
sağlıklı bir servisi yeniden başlatmak sorunu büyütür — o durum `ready` ile ifade edilir.

## 10. Correlation ID

- Gateway her isteğe bir `X-Correlation-Id` atar (varsa gelen değeri korur).
- Servisler arası her çağrıda ve her event payload'ında taşınır.
- **Her log satırında bulunur.**

Phase 10'dan itibaren zorunlu. Sonradan eklemek her servise, her log çağrısına ve her
event şemasına dokunmak demektir.

## 11. Yasak

- **Poz ve görüntü verisi kabul edilmez.** ADR 0002: landmark cihazdan çıkmaz. Backend
  yalnızca türetilmiş sayı alır — tekrar sayısı, süre, ROM, form hatası **adı**.
- **Başka servisin veritabanına erişim yok.** ADR 0005, istisnasız.
- **Loglarda hassas veri yok**: parola, token, e-posta. Kullanıcı `user_id` ile anılır.
- **Sır kodda yok**: ortam değişkeni, `.env.example` örnek değerlerle.
