"""Servislerin ortak Firebase katmanı (ADR 0019).

Her servis ayrı paket olarak kalır; bu paket yalnızca bağlantı, kimlik doğrulama
ve olay (outbox) altyapısını paylaşır. İş mantığı buraya girmez.
"""

from nabiz_firebase.firestore import FirestoreDatabase, firestore_client, run_contended_transaction
from nabiz_firebase.identity import user_uuid_for

__all__ = ["FirestoreDatabase", "firestore_client", "run_contended_transaction", "user_uuid_for"]
