"""Kimlik ara katmanı — `nabiz_firebase.auth.FirebaseAuthMiddleware` (ADR 0019).

Postgres dalında bu dosya `security.py`'yi (bcrypt, doğrulama kodu, refresh
token hash'i) ölçüyordu; o mantık Firebase Auth'a taşındı. Güvenlik yüzeyi
artık şu: servislerin güvendiği `X-User-Id` başlığını YALNIZCA doğrulanmış bir
Firebase ID token'ı üretebilmeli.

Firebase Auth emülatörü koşmadığı için token doğrulaması (`verify_id_token`)
sahteyle değiştiriliyor; test edilen şey ara katmanın davranışı — başlık
temizliği, 401 biçimi, UUID eşlemesi, hesap kaydı — Google'ın imza kontrolü değil.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio


def token_for(firebase_uid: str, *, email: str = "a@example.com", verified: bool = True) -> str:
    return f"valid|{firebase_uid}|{email}|{int(verified)}"


@pytest.fixture
def fake_firebase(monkeypatch):
    from nabiz_firebase import auth as firebase_auth

    claims_set: list[tuple[str, uuid.UUID]] = []
    deleted: list[str] = []

    def verify(token: str) -> dict:
        parts = token.split("|")
        if parts[0] != "valid":
            raise ValueError("ExpiredIdTokenError")
        return {"uid": parts[1], "email": parts[2], "email_verified": parts[3] == "1", "exp": 2_000_000_000}

    monkeypatch.setattr(firebase_auth, "verify_id_token", verify)
    monkeypatch.setattr(firebase_auth, "set_uuid_claim", lambda uid, user_id: claims_set.append((uid, user_id)))
    monkeypatch.setattr(firebase_auth, "delete_firebase_user", lambda uid: deleted.append(uid))
    monkeypatch.setattr(firebase_auth, "registry", firebase_auth.AccountRegistry())
    return {"claims": claims_set, "deleted": deleted}


@pytest_asyncio.fixture
async def gateway(api, fake_firebase):
    """auth-service'i tek süreçli giriş noktasının yapacağı gibi ara katmanla sarar."""
    from nabiz_firebase import auth as firebase_auth

    api("auth")
    from app.main import app

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=firebase_auth.FirebaseAuthMiddleware(app, registry=firebase_auth.registry)),
        base_url="http://test",
    )
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def firebase_uid():
    from nabiz_firebase import firestore_client, user_uuid_for

    uid = f"test-{uuid.uuid4().hex[:20]}"
    yield uid
    await firestore_client().collection("auth_accounts").document(str(user_uuid_for(uid))).delete()


async def test_gecerli_token_kimlik_basliklarini_URETIR(gateway, firebase_uid, fake_firebase):
    from nabiz_firebase import user_uuid_for

    response = await gateway.get("/v1/auth/me", headers={"Authorization": f"Bearer {token_for(firebase_uid)}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(user_uuid_for(firebase_uid))
    assert body["email"] == "a@example.com"
    assert body["email_verified"] is True
    assert body["status"] == "ACTIVE"
    assert isinstance(body["created_at"], int)
    # İlk görüşte custom claim (Firestore kuralları için) yazıldı, ikinci
    # istekte tekrar yazılmıyor (önbellek).
    await gateway.get("/v1/auth/me", headers={"Authorization": f"Bearer {token_for(firebase_uid)}"})
    assert fake_firebase["claims"] == [(firebase_uid, user_uuid_for(firebase_uid))]


async def test_SAHTE_X_User_Id_basligi_SILINIR(gateway, firebase_uid):
    """Token'sız bir istek başkasının kimliğini başlıkla taşıyamamalı."""
    victim = str(uuid.uuid4())
    response = await gateway.get("/v1/auth/me", headers={"X-User-Id": victim})
    assert response.status_code == 401

    # Geçerli token + sahte başlık: token'daki kimlik kazanır.
    from nabiz_firebase import user_uuid_for

    mixed = await gateway.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {token_for(firebase_uid)}", "X-User-Id": victim}
    )
    assert mixed.json()["id"] == str(user_uuid_for(firebase_uid))


@pytest.mark.parametrize("authorization", ["Bearer expired-token", "Basic abc", "Bearer"])
async def test_gecersiz_token_401_ve_sozlesme_bicimi(gateway, authorization):
    response = await gateway.get("/v1/auth/me", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_acik_uclar_tokensiz_calisir(gateway):
    assert (await gateway.get("/health/live")).status_code == 200


async def test_dogrulanmamis_eposta_PENDING_VERIFICATION_sonra_guncellenir(gateway, firebase_uid):
    headers = {"Authorization": f"Bearer {token_for(firebase_uid, verified=False)}"}
    first = (await gateway.get("/v1/auth/me", headers=headers)).json()
    assert (first["email_verified"], first["status"]) == (False, "PENDING_VERIFICATION")

    headers = {"Authorization": f"Bearer {token_for(firebase_uid, verified=True)}"}
    second = (await gateway.get("/v1/auth/me", headers=headers)).json()
    assert (second["email_verified"], second["status"]) == (True, "ACTIVE")
    assert second["created_at"] == first["created_at"]


async def test_introspect_ayni_basliklari_doner(gateway, firebase_uid):
    from nabiz_firebase import user_uuid_for

    ok = await gateway.get("/v1/auth/introspect", headers={"Authorization": f"Bearer {token_for(firebase_uid)}"})
    assert ok.status_code == 204
    assert ok.headers["X-User-Id"] == str(user_uuid_for(firebase_uid))
    assert ok.headers["X-Token-Exp"] == str(2_000_000_000 * 1000)
    assert (await gateway.get("/v1/auth/introspect")).status_code == 401
