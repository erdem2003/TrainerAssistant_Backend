"""Firestore görünümü (ADR 0019). Postgres havuzu ve .sql migration'ları kalktı.

Yerleşim — servisin kendi kök koleksiyonu altında, kullanıcı başına:

    analytics_users/{user_id}                       ÖZET dokümanı (rozetler) — aşağıda
    analytics_users/{user_id}/facts/{workout_id}    workout_facts satırı
    analytics_processed_events/{event_id}           idempotent tüketici kaydı

`workout_facts.workout_id PRIMARY KEY`'in karşılığı doküman kimliği: aynı
antrenmanın olayı ikinci kez işlense de ikinci doküman oluşamaz.

Okuma bütçesi ve özet dokümanının gerekçesi: `app/repo/facts.py`.
"""

from __future__ import annotations

from nabiz_firebase import FirestoreDatabase

db = FirestoreDatabase(root="analytics")


def user_doc(user_id):
    return db.collection("users").document(str(user_id))
