"""security.py birim testleri."""

from __future__ import annotations

import pytest

from app import security


class TestPassword:
    async def test_hash_ve_dogrulama(self):
        hashed = await security.hash_password("dogru-parola-123")
        assert await security.verify_password("dogru-parola-123", hashed)
        assert not await security.verify_password("yanlis-parola", hashed)

    async def test_ayni_parola_farkli_hash_uretir(self):
        """Salt her seferinde yeni: iki kullanıcı aynı parolayı seçse bile veritabanında aynı satır görünmez."""
        a = await security.hash_password("ayni-parola")
        b = await security.hash_password("ayni-parola")
        assert a != b

    async def test_kullanici_yoksa_da_dogrulama_calisir(self):
        """Sabit zaman: `None` hash ile de bcrypt çalışır."""
        assert not await security.verify_password("herhangi", None)

    async def test_72_bayttan_uzun_parola_REDDEDILIR(self):
        """bcrypt 72 bayttan sonrasını sessizce keser."""
        with pytest.raises(ValueError):
            await security.hash_password("a" * 73)


class TestCode:
    def test_kod_alti_hane(self):
        for _ in range(50):
            code = security.generate_code()
            assert len(code) == security.CODE_DIGITS
            assert code.isdigit()

    def test_kodlar_tekrar_etmiyor(self):
        """Zayıf bir rastgelelik kaynağı burada kendini belli ederdi."""
        assert len({security.generate_code() for _ in range(200)}) > 150

    async def test_kod_hash_dogrulama(self):
        code = security.generate_code()
        hashed = await security.hash_code(code)
        assert await security.verify_code(code, hashed)
        assert not await security.verify_code("000000" if code != "000000" else "111111", hashed)


class TestRefreshToken:
    def test_token_yuksek_entropili(self):
        tokens = {security.generate_refresh_token() for _ in range(200)}
        assert len(tokens) == 200
        assert all(len(t) >= 40 for t in tokens)

    def test_hash_deterministik(self):
        """Aynı token her zaman aynı hash — arama bunun üzerinden yapılıyor."""
        token = security.generate_refresh_token()
        assert security.hash_refresh_token(token) == security.hash_refresh_token(token)

    def test_farkli_token_farkli_hash(self):
        a = security.generate_refresh_token()
        b = security.generate_refresh_token()
        assert security.hash_refresh_token(a) != security.hash_refresh_token(b)


class TestEmailNormalize:
    def test_bosluk_ve_buyuk_harf_temizlenir(self):
        assert security.normalize_email("  Test@Example.COM ") == "test@example.com"

    def test_ayni_adres_ayni_bicime_iner(self):
        """Aynı adresle iki hesap açılmasını engelleyen şey bu."""
        variants = ["a@b.com", "A@B.com", " a@B.COM ", "A@b.CoM"]
        assert len({security.normalize_email(v) for v in variants}) == 1
