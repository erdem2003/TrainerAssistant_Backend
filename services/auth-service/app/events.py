"""Event turu ve topic sabitleri."""

from __future__ import annotations

# --- Event türleri -----------------------------------------------------------

EVENT_EMAIL_VERIFICATION_REQUESTED = "EmailVerificationRequested"
"""Kayıt ya da kod tekrar isteği sonrası. Payload: {email, code, expires_in_seconds}"""

EVENT_PASSWORD_RESET_REQUESTED = "PasswordResetRequested"
"""Parola sıfırlama isteği. Payload: {email, code, expires_in_seconds}"""

EVENT_PASSWORD_CHANGED = "PasswordChanged"
"""Parola değişti — sahibine bilgi maili. Payload: {email}

Kullanıcı bu maili beklemiyorsa hesabı ele geçirilmiş demektir; haber vermek
saldırıyı fark etmesinin en hızlı yolu.
"""

EVENT_ACCOUNT_DELETED = "AccountDeleted"
"""Hesap silindi. Payload: {user_id, email}

İKİ TÜKETİCİSİ VAR:
  1. e-posta worker'ı — sahibine "hesabın silindi" bilgisi
  2. Phase 11'de `workout` ve `analytics` — kendi verilerini temizlerler

İkincisi bu event'in asıl varlık sebebi: auth başka servisin veritabanına
dokunamaz (ADR 0005), o yüzden silme haberi event ile yayılır.
"""

# --- Topic adları ------------------------------------------------------------
# Biçim: <bounded-context>.<olay> — service-contract §8.

TOPIC_AUTH_EMAIL = "auth.email"

# Hesap yaşam döngüsü olayları. E-posta topic'inden AYRI: tüketicileri farklı
# (yalnızca mail değil, diğer servisler de dinleyecek).
TOPIC_AUTH_ACCOUNT = "auth.account"
