# Korumali location'larin ortak basliklari — `include` ile kullanilir.
#
# ★ NEDEN AYRI DOSYA, NEDEN SERVER SEVIYESINDE DEGIL ★
# nginx `proxy_set_header`i bir DIZI direktifi olarak ele alir ve ust
# seviyeden YALNIZCA mevcut seviyede HIC `proxy_set_header` yoksa devralir.
# Bu dosyanin var olma sebebi tam bunu ortadan kaldirmak: her korumali
# location zaten kendi `X-User-Id`/`X-Email-Verified` satirini yazmak
# ZORUNDA (auth_request'ten donen dogrulanmis degeri yazmasi gerekiyor) —
# ve bu satirin varligi, server bloğundaki asagidaki listenin TAMAMININ
# sessizce dusmesine yol aciyordu. Once bu HATA vardi: her korumali uc
# Host'u "user_upstream" gibi upstream adiyla goruyordu, X-Correlation-Id
# hic gitmiyordu (zincir kopuktu, service-contract §10 fiilen calismiyordu)
# ve Connection nginx varsayilanina (`close`) donup upstream keepalive'i
# (`keepalive 16`) devre disi birakiyordu.
#
# Duzeltme merkezi tek dosya: yeni bir korumali location eklerken bu
# `include` satirini unutmak, o location'i ayni hataya geri dusurur — ama
# hatirlaninca tek satir yeter, altı satırı yeniden yazmak gerekmez.
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Correlation-Id  $correlation_id;
proxy_http_version 1.1;
proxy_set_header Connection "";
