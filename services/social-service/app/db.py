"""Firestore görünümü (ADR 0019). Postgres havuzu ve .sql migration'ları kalktı.

Yerleşim — servisin kendi `social_` kök koleksiyonları:

    social_profiles/{user_id}                   {username, username_lower, display_name, avatar_seed, social_enabled, ...}
    social_usernames/{username_lower}           KİLİT: {user_id, claimed_at} ya da {retired_at} (emekli ad)
    social_friendships/{low}_{high}             {user_low, user_high, users:[low,high], status, requested_by, ...}
    social_posts/{post_id}                      {author_id, workout_id, note, status, post_type, photo_path, has_clip,
                                                 created_at, feed_at | pending_since}
    social_workout_posts/{author}_{workout}     KİLİT: (author_id, workout_id) UNIQUE → {post_id}
    social_post_likes/{post_id}_{user_id}       {post_id, user_id, created_at}
    social_post_comments/{comment_id}           {post_id, author_id, body, created_at, parent_comment_id}
    social_clips/{post_id}                      {landmark_sequence_z (zlib JSON), frame_count, form_errors, image_w/h}
    social_challenges/{challenge_id}            {creator_id, ..., participant_ids: [...]}
    social_kudos/{workout_id}_{giver_id}        {workout_id, giver_id, created_at}
    social_users/{user_id}/snapshots/{wid}      workout_snapshots satırı (olay izdüşümü)
    social_users/{user_id}/notifications/{key}  bildirim — key = {type}_{actor}_{subject} (doğal anahtar)
    social_workout_owners/{workout_id}          {user_id} — küresel "bu antrenman kimin" dizini
    social_deleted_users/{user_id}              silinen kullanıcı tombstone'u
    social_processed_events/{event_id}          idempotent tüketici kaydı

★ BİLEŞİK İNDEKS YOK ★ Her sorgu ya tek alanlı (otomatik) indeksle ya da
doküman kimliğiyle çalışıyor; bu yüzden `firestore.indexes.json` dağıtımı
gerekmiyor ve emülatörün yakalayamadığı "üretimde indeks eksik" hatası
oluşamıyor. Bunun için kullanılan iki desen:
  - YALNIZCA-DURUMDA-VAR alan: `feed_at` yalnızca VISIBLE gönderide,
    `pending_since` yalnızca PENDING_SNAPSHOT'ta. "status == X ORDER BY t"
    (bileşik) yerine "ORDER BY feed_at" (tek alan) — Firestore sıralama alanını
    taşımayan dokümanı zaten döndürmüyor.
  - Kullanıcıya göre aralık sorguları (snapshot'lar) kullanıcının ALT
    koleksiyonunda: "user_id == X AND started_at aralığı" bileşik indeks
    isterdi, alt koleksiyonda yalnızca `started_at` aralığı kalıyor.

★ UNIQUE KISITLARININ KARŞILIĞI ★ Deterministik doküman kimlikleri:
kullanıcı adı kilidi, kanonik arkadaşlık çifti, beğeni/kudos çifti,
(yazar, antrenman) gönderi kilidi, bildirim doğal anahtarı.
"""

from __future__ import annotations

from nabiz_firebase import FirestoreDatabase

db = FirestoreDatabase(root="social")


def user_doc(user_id):
    return db.collection("users").document(str(user_id))
