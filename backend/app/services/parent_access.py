from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import get_parent_auth, validate_pin, verify_pin_hash


async def require_parent_pin(session: AsyncSession, pin: str | None) -> None:
    if not pin:
        raise HTTPException(status_code=403, detail="此操作需要先验证家长 PIN。")
    try:
        normalized_pin = validate_pin(pin)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="家长 PIN 格式不正确。") from exc
    auth = await get_parent_auth(session)
    if auth is None or not verify_pin_hash(normalized_pin, auth.pin_hash):
        raise HTTPException(status_code=403, detail="家长 PIN 验证失败，请重新进入家长模式。")
