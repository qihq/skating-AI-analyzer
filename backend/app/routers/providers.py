from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AIProvider, Analysis
from app.schemas import ProviderCreate, ProviderMetricPublic, ProviderPublic, ProviderTestResponse, ProviderUpdate, VisionVoteConfig
from app.services.providers import activate_provider, encrypt_api_key, mask_api_key, test_provider_connectivity
from app.services.provider_metrics import summarize_provider_metrics
from app.services.vision_vote_config import load_vision_vote_config, save_vision_vote_config


router = APIRouter(prefix="/api/providers", tags=["providers"])

VALID_SLOTS = {"vision", "vision_path_a", "vision_path_b", "report"}


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


@router.get("/metrics", response_model=list[ProviderMetricPublic])
async def get_provider_metrics(
    days: int = Query(default=30, ge=1, le=3650),
    analysis_profile: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[ProviderMetricPublic]:
    day_value = days if isinstance(days, int) else 30
    profile_value = analysis_profile if isinstance(analysis_profile, str) and analysis_profile.strip() else None
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, day_value))
    query = (
        select(Analysis)
        .where(Analysis.status == "completed", Analysis.created_at >= cutoff)
        .order_by(Analysis.created_at.desc())
    )
    if profile_value:
        query = query.where(Analysis.analysis_profile == profile_value)

    result = await session.execute(query)
    analyses = list(result.scalars().all())
    if not analyses:
        return []

    vision_structured_items = [analysis.vision_structured if isinstance(analysis.vision_structured, dict) else None for analysis in analyses]
    cross_validation_items = [analysis.cross_validation if isinstance(analysis.cross_validation, dict) else None for analysis in analyses]
    metrics_report = summarize_provider_metrics(vision_structured_items, cross_validation_items)
    providers = metrics_report.get("providers", {}) if isinstance(metrics_report, dict) else {}

    if not isinstance(providers, dict):
        return []

    recommendations = metrics_report.get("recommendations", []) if isinstance(metrics_report, dict) else []
    recommendation_map = {
        str(item).split(":", 1)[-1]: str(item)
        for item in recommendations
        if isinstance(item, str) and ":" in item
    }

    return [
        ProviderMetricPublic(
            provider=provider,
            sample_count=metrics.get("sample_count", 0),
            json_valid_rate=metrics.get("json_valid_rate", 0.0),
            avg_effective_weight=metrics.get("avg_effective_weight", 0.0),
            conflict_rate=metrics.get("conflict_rate", 0.0),
            failure_rate=metrics.get("failure_rate", 0.0),
            recommendation=recommendation_map.get(provider),
        )
        for provider, metrics in sorted(providers.items())
        if isinstance(metrics, dict)
    ]


@router.get("/vision-vote/config", response_model=VisionVoteConfig)
async def get_vision_vote_config() -> VisionVoteConfig:
    return VisionVoteConfig(**load_vision_vote_config())


@router.put("/vision-vote/config", response_model=VisionVoteConfig)
async def update_vision_vote_config(
    payload: VisionVoteConfig,
    session: AsyncSession = Depends(get_session),
) -> VisionVoteConfig:
    provider_ids = [payload.primary_provider_id, payload.secondary_provider_id]
    unique_ids = {provider_id for provider_id in provider_ids if provider_id}
    if unique_ids:
        result = await session.execute(
            select(AIProvider.id).where(AIProvider.slot == "vision", AIProvider.id.in_(unique_ids))
        )
        found_ids = {row[0] for row in result.all()}
        missing_ids = unique_ids - found_ids
        if missing_ids:
            raise HTTPException(status_code=400, detail="vision vote provider must belong to slot=vision.")

    saved = save_vision_vote_config(payload.model_dump())
    return VisionVoteConfig(**saved)


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
        vision_model=payload.vision_model,
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
