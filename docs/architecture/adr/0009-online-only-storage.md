# ADR 0009 — Online-Only Depolama, Tek Gerçek Kaynak PostgreSQL

**Durum:** Kabul · Phase 10
**Geçersiz kılar:** [ADR 0007](0007-anonymous-local-identity.md)

## Bağlam

ADR 0007 anonim yerel kimlik öngörüyordu: uygulama hesapsız açılır, veriler cihazda
(Room) durur, Phase 10'da hesap açılınca sunucuya devredilir. ADIM 19-20'de bu tasarım
uygulandı ve çalışıyor.

Phase 10'un başında sahip, bu kararı değiştirdi: **veriler tek bir yerde, PostgreSQL'de
yaşasın.** Gerekçe, iki yerde veri tutmanın senkron karmaşıklığını taşımak istememek.

Karar alınmadan önce offline-first'ün kaybedileceği açıkça belirtildi ve alternatifler
(Postgres kaynak + küçük yerel kuyruk; mevcut tam kopya) sunuldu. Sahip online-only'de
ısrar etti.

## Karar

**Yerel veritabanı yoktur. Tek gerçek kaynak PostgreSQL'dir. Giriş zorunludur.**

```
Uygulama açılır  →  oturum var mı?
                    ├─ hayır → login / kayıt ekranı   (uygulama kullanılamaz)
                    └─ evet  → kamera; her antrenman sonunda sunucuya yazılır
```

- Room ve tüm `data/` katmanı mobil taraftan kaldırılır
- Geçmiş, ilerleme ve profil ekranları veriyi **sunucudan** okur
- `user_id` JWT'den gelir; cihazda anonim kimlik üretilmez
- Hesap devri (claim) gereksinimi **ortadan kalkar** — devredilecek anonim veri yok

## Gerekçe

**Tek kaynak, tek doğruluk.** İki yerde tutulan veri er ya da geç ayrışır; hangisinin
doğru olduğuna karar veren bir çakışma çözümü gerekir. Online-only bu sınıf hatayı
tanım gereği ortadan kaldırır.

**Senkron kodu yazılmaz.** `syncState`, kuyruk, yeniden deneme, çakışma çözümü — hiçbiri
gerekmiyor. Phase 10'un kapsamı belirgin şekilde küçülüyor.

**Çok cihaz kendiliğinden çalışır.** Kullanıcı telefonunu değiştirdiğinde verisi zaten
sunucuda; ADR 0007'nin "cihaz değişikliğinde veri taşınmaz" kısıtı kalkar.

## Sonuçlar

### Kabul edilen bedeller

Bunlar bilinen ve kabul edilmiş maliyetlerdir:

- **Bağlantı yokken antrenman kaydedilemez.** Spor salonu bodrumu, park, kırsal alan —
  şınav çekilir ama set kaybolur. Bu, ürünün kullanıldığı yerlerin bir kısmını dışarıda
  bırakır.
- **İlk açılışta login ekranı.** ADR 0007'nin sayfalarca gerekçelendirdiği drop-off
  riski geri geliyor: kullanıcı değeri görmeden hesap açmak zorunda.
- **Her antrenman sonu bir ağ çağrısına bağlı.** Çağrı başarısız olursa kullanıcıya
  hata gösterilir; yeniden deneme kuyruğu olmadığı için veri kurtarılamaz.
- **ADR 0005'in bir çıkış kriteri geçersiz olur:** "anonim profil hesaba devrediliyor
  (claim)". Phase 10 bu kriter olmadan kapanır.

### Değişmeyen

**ADR 0002 tam olarak geçerlidir.** Analiz cihazda kalır; sunucuya yalnızca türetilmiş
sayılar gider — tekrar sayısı, süre, ROM, form hatası **adı**. Görüntü ve landmark
verisi cihazdan çıkmaz. Bu ADR depolamayı değiştirir, analizi değil.

### Geri dönüş yolu

Bu karar tersine çevrilebilir ve maliyeti bilinir: yerel bir kuyruk tablosu + gönderim
mantığı eklemek. Veri sözleşmesi (`WorkoutRecord`, `UserProfile`) değişmediği için
sunucu tarafı etkilenmez. Sahada "kaydedemedim" şikâyeti gelirse ilk yapılacak budur.

## Reddedilen Alternatifler

**Postgres kaynak + küçük yerel kuyruk.**
Reddedildi. Sunucu gerçeğin kaynağı olur, ekranlar sunucudan okur, ama gönderilmemiş
antrenmanlar küçük bir yerel tabloda bekler. Sahibin istediği "veriler Postgres'te"
sonucunu verirken çevrimdışı veri kaybını da önlerdi. Sahip yerel depo istemediği için
reddedildi.

**Mevcut yapıyı korumak (Room tam kopya).**
Reddedildi: iki yerde veri tutmanın senkron karmaşıklığı istenmiyor.
