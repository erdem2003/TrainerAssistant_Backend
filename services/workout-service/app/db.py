"""Firestore görünümü (ADR 0019). Postgres havuzu ve .sql migration'ları kalktı.

Yerleşim — servisin kendi kök koleksiyonu altında:

    workout_users/{user_id}/workouts/{workout_id}   antrenmanın TAMAMI (aşağıda)
    workout_users/{user_id}/plan/{yyyy-MM-dd}       {items: [...], updated_at}
    workout_workout_ids/{workout_id}                {user_id, content_hash} — küresel kimlik kaydı
    workout_outbox/{event_id}                       olay kuyruğu (nabiz_firebase.outbox)
    workout_processed_events/{event_id}             idempotent tüketici kaydı

★ ANTRENMAN TEK DOKÜMAN ★ Postgres'teki workouts/sets/reps/rep_form_errors
dört tablosu tek dokümanda iç içe duruyor: `sets[].reps[].form_errors`. Tek
antrenman her zaman bir bütün olarak yazılıyor ve okunuyor; ayrı dokümanlar
detay başına N okuma demekti (kota). Boyut sınırı (1 MiB) pratikte uzak: tekrar
başına ~150 bayt, 1000 tekrar ~150 KB.

Liste/istatistik/plan sorgularının ihtiyacı olan toplamlar da (total_sets,
total_reps, reps_with_errors, active_seconds, best_set_reps, form_errors)
yazımda BİR KEZ hesaplanıp dokümana konuyor — Postgres'te her okumada JOIN +
COUNT ile üretiliyordu. Sorgular `select()` ile yalnızca bu alanları çekiyor.

★ NEDEN AYRI KİMLİK KAYDI ★ `workouts.id` Postgres'te KÜRESEL birincil
anahtardı: başka kullanıcının id'si ile gelen istek 404 alıyordu. Antrenman
kullanıcının altında durduğu için aynı id başka kullanıcının altında da
oluşabilirdi; `workout_workout_ids/{id}` aynı transaction'da `create()` ile
yazılıp bu küresel tekliği geri getiriyor.

Zaman: `started_at`/`ended_at` Firestore zaman damgası (aralık sorgusu tek
alanlı otomatik indeksle); set içi zamanlar epoch ms (istemcinin gönderdiği
biçim, yalnızca geri döndürülüyor).
"""

from __future__ import annotations

from nabiz_firebase import FirestoreDatabase

db = FirestoreDatabase(root="workout")


def user_doc(user_id):
    return db.collection("users").document(str(user_id))
