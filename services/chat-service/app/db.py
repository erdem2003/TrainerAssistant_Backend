"""Firestore görünümü (ADR 0019). Postgres havuzu ve .sql migration'ları kalktı.

Yerleşim — servisin kendi `chat_` kök koleksiyonları:

    chat_conversations/{conversation_id}
        user_low, user_high, participants: [low, high]
        next_seq                 bir sonraki mesajın sırası (atomik atama)
        last_message             {id, body, sender_id, created_at, redacted} | null
        last_message_at          liste sıralaması
        reads.{user_id}          {last_read_seq, last_read_at, left_at}
    chat_conversations/{conversation_id}/messages/{message_id}
        seq, sender_id, body, content_hash, created_at, redacted_at
    chat_processed_events/{event_id}

★ OKUMA MOBİLDE, DİNLEYİCİYLE (ADR 0019 karar 5) ★ Mesaj ve okundu bilgisi
Redis pub/sub + WebSocket yerine doğrudan bu dokümanlara yazılıyor; istemci
`messages` alt koleksiyonunu ve konuşma dokümanını snapshot dinleyicisiyle
izliyor. YAZMA hâlâ bu servisten (idempotency, sıra, arkadaşlık kontrolü).

★ KONUŞMA KİMLİĞİ DETERMİNİSTİK ★ Postgres'te rastgele UUID + `UNIQUE
(user_low, user_high)` vardı. Burada kimlik kanonik çiftten türetiliyor
(UUIDv5): get-or-create tek `create()`, yarışta ikinci kayıt oluşamaz, kilit
dokümanı gerekmez. Erişim yine katılımcı kontrolüyle (kimliği bilmek yetmez).

`next_seq`, `last_message` ve okuma durumu konuşma dokümanında: liste ekranı
konuşma başına TEK doküman okur (Postgres'teki LATERAL son-mesaj sorgusunun
karşılığı), okunmamış sayısı `next_seq - 1 - last_read_seq`.
"""

from __future__ import annotations

from nabiz_firebase import FirestoreDatabase

db = FirestoreDatabase(root="chat")
