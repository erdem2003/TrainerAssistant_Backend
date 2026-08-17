"""Gateway'in dogruladigi kimligi X-User-Id basligindan okur (service-contract §2)."""

from __future__ import annotations

import uuid

from app.errors import invalid_token


def require_user_id(raw: str | None) -> uuid.UUID:
    if not raw:
        raise invalid_token()
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise invalid_token() from None
