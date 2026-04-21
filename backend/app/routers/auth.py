from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ParentAuth
from app.schemas import ChangePinRequest, ChangePinResponse, HasPinResponse, PinPayload, VerifyPinResponse
from app.services.auth import get_parent_auth, hash_pin, validate_pin, verify_pin_hash


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/has-pin", response_model=HasPinResponse)
async def has_pin(session: AsyncSession = Depends(get_session)) -> HasPinResponse:
    auth = await get_parent_auth(session)
    return HasPinResponse(has_pin=auth is not None, pin_length=auth.pin_length if auth else 4)


@router.post("/setup-pin", response_model=HasPinResponse)
async def setup_pin(payload: PinPayload, session: AsyncSession = Depends(get_session)) -> HasPinResponse:
    try:
        pin = validate_pin(payload.pin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    auth = await get_parent_auth(session)
    if auth is None:
        auth = ParentAuth(pin_hash=hash_pin(pin), pin_length=len(pin))
        session.add(auth)
    else:
        auth.pin_hash = hash_pin(pin)
        auth.pin_length = len(pin)
    await session.commit()
    return HasPinResponse(has_pin=True, pin_length=len(pin))


@router.post("/verify-pin", response_model=VerifyPinResponse)
async def verify_pin(payload: PinPayload, session: AsyncSession = Depends(get_session)) -> VerifyPinResponse:
    try:
        pin = validate_pin(payload.pin)
    except ValueError:
        return VerifyPinResponse(valid=False)

    auth = await get_parent_auth(session)
    if auth is None:
        return VerifyPinResponse(valid=False)
    return VerifyPinResponse(valid=verify_pin_hash(pin, auth.pin_hash))


@router.post("/change-pin", response_model=ChangePinResponse)
async def change_pin(payload: ChangePinRequest, session: AsyncSession = Depends(get_session)) -> ChangePinResponse:
    try:
        old_pin = validate_pin(payload.old_pin)
        new_pin = validate_pin(payload.new_pin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    auth = await get_parent_auth(session)
    if auth is None or not verify_pin_hash(old_pin, auth.pin_hash):
        return ChangePinResponse(success=False, reason="旧PIN不正确")

    auth.pin_hash = hash_pin(new_pin)
    auth.pin_length = len(new_pin)
    await session.commit()
    return ChangePinResponse(success=True)
