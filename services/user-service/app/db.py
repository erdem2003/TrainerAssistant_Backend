"""Firestore görünümü (ADR 0019). Postgres havuzu ve .sql migration'ları kalktı.

Yerleşim — servisin kendi kök koleksiyonu altında, kullanıcı başına:

    user_users/{user_id}                                  profil alanları (profiles satırı)
    user_users/{user_id}/measurements/{yyyy-MM-dd}        {weight_kg, waist_cm, arm_cm, updated_at}
    user_users/{user_id}/calibration/{exercise_id}        {sample_count, measured_values, calibrated_at}
    user_processed_events/{event_id}                      idempotent tüketici kaydı

Profil kök dokümanın KENDİSİ: `profiles.user_id PRIMARY KEY`'in karşılığı, ayrı
bir profil kimliği yok. Alt koleksiyonlar kök doküman hiç yazılmamışken de
var olabilir (Firestore'da "hayalet" üst doküman) — profil okuması bu yüzden
`snap.exists`'e bakıyor, alt koleksiyonun varlığına değil.

`(user_id, measured_date)` ve `(user_id, exercise_id)` UNIQUE kısıtlarının
karşılığı doküman kimliğinin kendisi.
"""

from __future__ import annotations

from nabiz_firebase import FirestoreDatabase

db = FirestoreDatabase(root="user")


def user_doc(user_id):
    return db.collection("users").document(str(user_id))
