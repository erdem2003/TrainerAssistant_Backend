# ADR 0007 — Anonim Yerel Kimlik, Sonradan Hesap Devri

**Durum:** Kabul · Phase 0

## Bağlam

Kimlik kavramına Phase 6'dan (veri toplama) itibaren ihtiyaç var: kalibrasyon kişiye özel,
dataset user-based split'e dayanıyor, antrenman geçmişi kullanıcıya ait. Ancak auth
altyapısı Phase 10'da kuruluyor.

Soru şu: giriş/kayıt/e-posta doğrulama akışı öne mi çekilmeli, yoksa kimlik başka türlü
mü çözülmeli?

## Karar

**İlk açılışta cihazda anonim `user_id` (UUID v4) üretilir. Giriş ekranı yoktur.**

Kalibrasyon, antrenman geçmişi ve dataset kayıtları bu id ile çalışır. Phase 10'da kullanıcı
hesap oluşturduğunda anonim profil hesaba **devredilir (claim)** — veri kaybı ve migration yoktur.

```
İlk açılış  →  local_user_id = UUID()   (cihazda, hesap yok)
               kalibrasyon · antrenman · dataset  ← bu id ile
Phase 10    →  "Hesap oluştur"
               auth-service: hesap açılır
               local_user_id → account_id eşlemesi kurulur
               yerel veri senkronize edilir
```

## Gerekçe

**1. Belirsiz olan iş önce yapılır.**
Login/kayıt/e-posta doğrulama çözülmüş bir problemdir; nasıl yapılacağı bellidir, riski
yoktur. Pose analizinin çalışıp çalışmayacağı belirsizdir. Belirsiz olanı sona bırakmak,
haftalarca auth yazdıktan sonra çekirdeğin çalışmadığını keşfetme riskini taşır.

**2. Kimlik ile auth aynı şey değil.**
İhtiyacımız olan "bu veriler kime ait" sorusunun cevabı — "bu kişi gerçekten o mu"
sorusununki değil. Anonim UUID birincisini tam olarak karşılıyor.

**3. Ürün açısından da doğru.**
Fitness uygulamasını açar açmaz kayıt ekranı görmek en yüksek terk (drop-off) sebeplerinden
biridir. Kullanıcı önce değeri görmeli, sonra hesap açmalı.

**4. Play Store engeli yok.**
Hesapsız uygulama yayınlanabilir. Hesap zorunluluğu geldiğinde Google'ın hesap silme
gereksinimi devreye girer — o da zaten auth servisiyle birlikte gelir.

**5. Migration borcu oluşmuyor.**
`user_id` ilk günden veri şemasında olduğu için, hesap eklendiğinde tablo yapısı değişmez;
sadece bir eşleme kaydı eklenir.

## Sonuçlar

- `user_id` ilk günden Room şemasında ve dataset şemasında bulunur
- Dataset'te bu id **pseudonymized** kalır; gerçek kimlikle eşleşmesi backend tarafında tutulur
- Cihaz değişikliğinde veri taşınmaz — hesap oluşturulana kadar bu bilinen ve kabul edilen
  bir kısıttır, kullanıcıya açıkça belirtilir
- `backend-engineer` agent'ı Phase 10'da oluşturulur; daha erken gerek yok
- `auth-service` hesap devri (claim) akışını desteklemek zorundadır — bu, Phase 10'da
  sonradan eklenen değil, baştan planlanan bir gereksinimdir

## Reddedilen Alternatifler

**Auth'u Phase 1'e çekmek.**
Reddedildi: projenin en belirsiz kısmı (CV) en sona kalır. Ayrıca ilk haftalarda gösterilebilir
tek çıktı bir login ekranı olur — bitirme projesi için de zayıf bir çıktı.

**Auth'u Phase 5.5'e çekmek (CV prototipleri sonrası, veri toplamadan önce).**
Reddedildi ama makul bir alternatifti: dataset'i gerçek hesaplarla toplamak çok cihazlı
senkronu erken çalıştırırdı. Anonim UUID zaten user-based split için yeterli olduğundan
ek fayda maliyeti karşılamıyor.

**Kimliksiz çalışmak (her şey cihaz-lokal, user_id yok).**
Reddedildi: user-based split ve kişisel kalibrasyon bir kimlik anahtarı gerektiriyor.
Sonradan eklemek, toplanmış tüm veriyi kullanılamaz hale getirirdi.

**Cihaz kimliği (ANDROID_ID) kullanmak.**
Reddedildi: gizlilik açısından sorunlu, Play Store politikalarıyla riskli, ve fabrika
ayarlarına dönüşte değişiyor. Uygulamanın kendi ürettiği UUID hem daha temiz hem taşınabilir.
