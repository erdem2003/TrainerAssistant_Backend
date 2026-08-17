"""Event turu ve topic sabitleri (service-contract §8)."""

from __future__ import annotations

# Antrenman kaydedildiginde yayinlanir. Phase 11'de analytics-service bunu
# dinleyip streak/rekor/trend modelini kuracak.
EVENT_WORKOUT_COMPLETED = "WorkoutCompleted"

# Topic adi: <bounded-context>.<olay>
TOPIC_WORKOUT_SESSION = "workout.session"

# auth-service'ten gelen; hesap silindiginde antrenmanlari temizlemek icin.
EVENT_ACCOUNT_DELETED = "AccountDeleted"
