"""Firestore görünümü (ADR 0019). Postgres havuzu ve .sql migration'ları kalktı.

Kimlik artık Firebase Auth'ta (ADR 0019 karar 3): parola, doğrulama kodu,
refresh token ve e-posta outbox'ı tabloları KALKTI. auth-service'in tuttuğu
tek şey kimlik eşlemesi:

    auth_accounts/{user_uuid}   {firebase_uid, email, email_verified, created_at}

`user_uuid = nabiz_firebase.user_uuid_for(firebase_uid)` — servislerin her
yerde taşıdığı UUID. Doküman ilk kimliği doğrulanmış istekte
`nabiz_firebase.auth.FirebaseAuthMiddleware` tarafından yazılıyor; bu servis
okuyor ve hesap silmede kaldırıyor.
"""

from __future__ import annotations

from nabiz_firebase import FirestoreDatabase

db = FirestoreDatabase(root="auth")
