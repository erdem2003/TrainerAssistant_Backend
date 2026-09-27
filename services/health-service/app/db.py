"""Firestore görünümü (ADR 0019). Postgres havuzu ve .sql migration'ları kalktı.

Yerleşim — servisin kendi kök koleksiyonu altında, kullanıcı başına:

    health_users/{user_id}/water/{yyyy-MM-dd}   {amount_ml, updated_at}
    health_users/{user_id}/sleep/{yyyy-MM-dd}   {minutes, updated_at}
    health_processed_events/{event_id}          idempotent tüketici kaydı

Doküman kimliği tarihin kendisi: `(user_id, log_date)` UNIQUE kısıtının
Firestore karşılığı — aynı gün için ikinci doküman oluşamaz. Aralık sorgusu da
kimlik üzerinden (ISO tarih sözlük sırasıyla kronolojik) — bileşik indeks gerekmez.
"""

from __future__ import annotations

from nabiz_firebase import FirestoreDatabase

db = FirestoreDatabase(root="health")


def user_doc(user_id):
    return db.collection("users").document(str(user_id))
