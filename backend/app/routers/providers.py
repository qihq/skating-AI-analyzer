from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AIProvider
from app.schemas import ProviderCreate, ProviderPublic, ProviderTestResponse, ProviderUpdate
from app.services.providers import activate_provider, encrypt_api_key, mask_api_key, test_provider_connectivity


router = APIRouter(prefix="/api/providers", tags=["providers"])

VALID_SLOTS = {"vision", "report"}


def serialize_provider(provider: AIProvider) -> ProviderPublic:
    return ProviderPublic(
        id=provider.id,
        slot=provider.slot,
        name=provider.name,
        provider=provider.provider,
        base_url=provider.base_url,
        model_id=provider.model_id,
        vision_model=provider.vision_model,
        api_key=mask_api_key(provider.api_key),
        is_active=provider.is_active,
        notes=provider.notes,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@router.get("/", response_model=list[ProviderPublic])
async def list_providers(session: AsyncSession = Depends(get_session)) -> list[ProviderPublic]:
    result = await session.execute(
        select(AIProvider).order_by(AIProvider.slot.asc(), AIProvider.is_active.desc(), AIProvider.created_at.asc())
    )
    return [serialize_provider(provider) for provider in result.scalars().all()]


@router.get("/{slot}/active", response_model=ProviderPublic)
async def get_active_provider(slot: str, session: AsyncSession = Depends(get_session)) -> ProviderPublic:
    if slot not in VALID_SLOTS:
        raise HTTPException(status_code=400, detail="slot 必须是 vision 或 report。")

    result = await session.execute(
        select(AIProvider).where(AIProvider.slot == slot, AIProvider.is_active.is_(True)).limit(1)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="当前 slot 没有激活供应商。")
    return serialize_provider(provider)


@router.post("/", response_model=ProviderPublic, status_code=status.HTTP_201_CREATED)
async def create_provider(payload: ProviderCreate, session: AsyncSession = Depends(get_session)) -> ProviderPublic:
    if payload.slot not in VALID_SLOTS:
        raise HTTPException(status_code=400, detail="slot 必须是 vision 或 report。")

    active_count = await session.scalar(
        select(func.count()).select_from(AIProvider).where(
            AIProvider.slot == payload.slot,
            AIProvider.is_active.is_(True),
        )
    )
    provider = AIProvider(
        slot=payload.slot,
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        model_id=payload.model_id,
        api_key=encrypt_api_key(payload.api_key),
        is_active=(active_count or 0) == 0,
        notes=payload.notes,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return serialize_provider(provider)


@router.patch("/{provider_id}", response_model=ProviderPublic)
async def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProviderPublic:
    provider = await session.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="供应商不存在。")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "api_key":
            setattr(provider, field, encrypt_api_key(value or ""))
        else:
            setattr(provider, field, value)

    await session.commit()
    await session.refresh(provider)
    return serialize_provider(provider)


@router.patch("/{provider_id}/activate", response_model=ProviderPublic)
async def activate_provider_route(provider_id: str, session: AsyncSession = Depends(get_session)) -> ProviderPublic:
    provider = await session.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="供应商不存在。")

    provider = await activate_provider(provider, session)
    return serialize_provider(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_provider(provider_id: str, session: AsyncSession = Depends(get_session)):
    provider = await session.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="供应商不存在。")

    replacement: AIProvider | None = None
    if provider.is_active:
        alternative_result = await session.execute(
            select(AIProvider)
            .where(AIProvider.slot == provider.slot, AIProvider.id != provider.id)
            .order_by(AIProvider.created_at.asc())
        )
        alternatives = list(alternative_result.scalars().all())
        if not alternatives:
            raise HTTPException(status_code=400, detail="不可删除该 slot 唯一的激活供应商。")
        replacement = alternatives[0]

    await session.delete(provider)
    if replacement is not None:
        replacement.is_active = True
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_id}/test", response_model=ProviderTestResponse)
async def test_provider(provider_id: str, session: AsyncSession = Depends(get_session)) -> ProviderTestResponse:
    provider = await session.get(AIProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="供应商不存在。")

    success, detail = await test_provider_connectivity(provider)
    return ProviderTestResponse(success=success, detail=detail)
