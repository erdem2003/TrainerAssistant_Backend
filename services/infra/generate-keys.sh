#!/usr/bin/env sh
# JWT icin RSA anahtar cifti uretir.
#
# NEDEN RS256: gateway token'i yalnizca PUBLIC key ile dogrular; private key
# auth-service'te kalir. HS256 olsaydi ayni gizli anahtari her dogrulayan
# servisle paylasmak gerekirdi ve token URETEBILEN servis sayisi artardi.
#
# Anahtarlar depoya GIRMEZ (.gitignore). Uretimde secret yoneticisinden gelir.
set -e
DIR="$(dirname "$0")/keys"
mkdir -p "$DIR"

if [ -f "$DIR/jwt_private.pem" ]; then
  echo "anahtarlar zaten var: $DIR"
  exit 0
fi

openssl genpkey -algorithm RSA -out "$DIR/jwt_private.pem" -pkeyopt rsa_keygen_bits:2048
openssl rsa -pubout -in "$DIR/jwt_private.pem" -out "$DIR/jwt_public.pem"
chmod 600 "$DIR/jwt_private.pem"
echo "anahtarlar uretildi: $DIR"
