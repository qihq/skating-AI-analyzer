from __future__ import annotations

import re

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ParentAuth


PIN_PATTERN = re.compile(r"^\d{4,6}$")


def validate_pin(pin: str) -> str:
    normalized = pin.strip()
    if not PIN_PATTERN.fullmatch(normalized):
        raise ValueError("PIN must be 4-6 digits.")
    return normalized


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_pin_hash(pin: str, pin_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except ValueError:
        return False


async def get_parent_auth(session: AsyncSession) -> ParentAuth | None:
    result = await session.execute(select(ParentAuth).order_by(ParentAuth.created_at.asc()).limit(1))
    return result.scalar_one_or_none()
