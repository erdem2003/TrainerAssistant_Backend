"""AdMob ödüllü reklam — sunucu tarafı doğrulama (SSV) imza kontrolü.

AdMob, kullanıcı videoyu bitirince ödül uç noktasına GET atar. Sorgu dizesinin
SON iki parametresi `signature` ve `key_id`; imzalanan mesaj `&signature=`'den
önceki her şey. İmza ECDSA (P-256, SHA-256), web-güvenli base64, DER biçimli.
Açık anahtarlar Google'ın yayımladığı listeden alınır ve önbelleklenir.

Belge: https://developers.google.com/admob/android/ssv

★ NEDEN SUNUCUDA ★ İstemciye güvenilseydi ("videoyu izledim" diye bir POST)
herkes ödülü videosuz alırdı. SSV isteğini yalnız Google imzalayabilir.
"""

from __future__ import annotations

import base64
import logging
import time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)

KEYS_URL = "https://www.gstatic.com/admob/reward/verifier-keys.json"
_KEY_TTL_SECONDS = 24 * 3600

_keys: dict[int, ec.EllipticCurvePublicKey] = {}
_keys_fetched_at = 0.0


class SsvError(Exception):
    """İmza/biçim geçersiz — istek ödül vermez."""


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


async def _load_keys(force: bool = False) -> dict[int, ec.EllipticCurvePublicKey]:
    global _keys, _keys_fetched_at
    if _keys and not force and time.monotonic() - _keys_fetched_at < _KEY_TTL_SECONDS:
        return _keys
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(KEYS_URL)
    response.raise_for_status()
    loaded: dict[int, ec.EllipticCurvePublicKey] = {}
    for entry in response.json().get("keys", []):
        key = serialization.load_pem_public_key(entry["pem"].encode())
        if isinstance(key, ec.EllipticCurvePublicKey):
            loaded[int(entry["keyId"])] = key
    _keys, _keys_fetched_at = loaded, time.monotonic()
    return _keys


def split_query(raw_query: str) -> tuple[bytes, bytes, int]:
    """(imzalanan mesaj, imza, key_id). Sıra AdMob sözleşmesi: imza ve key_id sonda."""
    marker = raw_query.find("&signature=")
    if marker <= 0:
        raise SsvError("signature yok")
    message = raw_query[:marker].encode()
    tail = dict(part.split("=", 1) for part in raw_query[marker + 1:].split("&") if "=" in part)
    try:
        return message, _b64url_decode(tail["signature"]), int(tail["key_id"])
    except (KeyError, ValueError) as exc:
        raise SsvError("signature/key_id bozuk") from exc


async def verify(raw_query: str) -> None:
    """İmza geçerli değilse `SsvError`. Bilinmeyen key_id'de anahtarlar bir kez tazelenir."""
    message, signature, key_id = split_query(raw_query)
    keys = await _load_keys()
    if key_id not in keys:
        keys = await _load_keys(force=True)
    key = keys.get(key_id)
    if key is None:
        raise SsvError(f"bilinmeyen key_id={key_id}")
    try:
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise SsvError("imza doğrulanamadı") from exc
