FROM nginx:1.27-alpine

# Varsayilan yapilandirmayi kaldir; kendi conf.d'miz gelsin.
RUN rm -f /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d/    /etc/nginx/conf.d/

EXPOSE 80

# 127.0.0.1 — `localhost` DEGIL.
#
# Konteyner icinde `localhost` once ::1'e (IPv6) cozuluyor, nginx ise varsayilan
# olarak yalnizca IPv4'te dinliyor (0.0.0.0:80). Sonuc "connection refused" ve
# tamamen saglikli bir servisin unhealthy gorunmesi.
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -qO- http://127.0.0.1/health/live || exit 1
