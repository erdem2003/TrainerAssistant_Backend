# `proxy_common.inc` ile AYNI, `Connection` satiri HARIC.
#
# NEDEN AYRI DOSYA: WebSocket location'i `Connection`'i upgrade icin
# $connection_upgrade'e YAZMAK zorunda (bkz. gateway.conf `/ws`). Ayni
# `proxy_set_header Connection` iki kez (once bos, sonra upgrade degeriyle)
# yazilsaydi ikinci deger kazanirdi ama bu, okuyanin "hangisi gecerli"
# sorusunu sormasina yol acardi — sessiz ama kirilgan. Iki kucuk dosya
# tutmak, bir satirlik kopya-hata riskinden daha ucuz.
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Correlation-Id  $correlation_id;
proxy_http_version 1.1;
