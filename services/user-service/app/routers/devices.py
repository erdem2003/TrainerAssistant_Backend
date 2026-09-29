"""Push bildirimi cihaz kaydı.

POST   /v1/users/me/devices   FCM token'ını bu hesaba bağlar (açılışta + token yenilenince)
DELETE /v1/users/me/devices   çıkışta token'ı bırakır (gövdede token — URL'de token loglanmasın)
"""

from __future__ import annotations

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, Field

from app.identity import require_user_id
from app.repo import devices, rewards

router = APIRouter(prefix="/v1/users/me/devices", tags=["devices"])


class DeviceIn(BaseModel):
    token: str = Field(min_length=20, max_length=4096)
    platform: str = Field(default="android", pattern="^(android|ios)$")


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def register_device(body: DeviceIn, x_user_id: str | None = Header(default=None)) -> None:
    user_id = require_user_id(x_user_id)
    await devices.register(user_id, body.token, body.platform, rewards.utc_now())


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(body: DeviceIn, x_user_id: str | None = Header(default=None)) -> None:
    user_id = require_user_id(x_user_id)
    await devices.unregister(user_id, body.token)
