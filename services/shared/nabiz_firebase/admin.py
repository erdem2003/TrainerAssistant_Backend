"""firebase-admin uygulaması — tek süreçte tek örnek (Auth + Storage).

Firestore için `firestore.py`'deki async istemci kullanılıyor; firebase-admin
yalnızca kimlik doğrulama (`auth.verify_id_token`, `auth.delete_user`) ve
Storage kovası için gerekli.

KİMLİK BİLGİSİ SIRASI `firestore.py` ile aynı:
1. `FIREBASE_SERVICE_ACCOUNT_JSON` (Render'da gizli değişken, JSON metni)
2. Application Default Credentials (`GOOGLE_APPLICATION_CREDENTIALS`)
Emülatör değişkenleri (`FIREBASE_AUTH_EMULATOR_HOST`, `STORAGE_EMULATOR_HOST`)
firebase-admin tarafından kendiliğinden okunuyor.
"""

from __future__ import annotations

import json
import logging
import os

import firebase_admin
from firebase_admin import credentials

from nabiz_firebase.firestore import DEFAULT_PROJECT

logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "nabiz-trainer.firebasestorage.app"


def firebase_app() -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass
    project = os.environ.get("FIREBASE_PROJECT_ID", DEFAULT_PROJECT)
    options = {
        "projectId": project,
        "storageBucket": os.environ.get("FIREBASE_STORAGE_BUCKET", DEFAULT_BUCKET),
    }
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    cred = credentials.Certificate(json.loads(raw)) if raw else None
    app = firebase_admin.initialize_app(cred, options)
    logger.info("firebase-admin açıldı project=%s", project)
    return app
