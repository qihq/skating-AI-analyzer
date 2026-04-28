from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas import ApiConnectionTestResponse
from app.services.analysis_errors import AnalysisErrorCode, classify_ai_failure
from app.services.providers import TINY_PNG_DATA_URL, default_extra_body, get_active_provider, request_text_completion


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/test-api", response_model=ApiConnectionTestResponse)
async def test_api_connection(session: AsyncSession = Depends(get_session)) -> ApiConnectionTestResponse:
    started = time.perf_counter()
    current_stage = "vision"
    try:
        vision_provider = await get_active_provider("vision", session)
        vision_client = AsyncOpenAI(
            api_key=vision_provider.api_key,
            base_url=vision_provider.base_url,
            timeout=30.0,
            max_retries=0,
        )
        await vision_client.chat.completions.create(
            model=vision_provider.model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请回复 ok。"},
                        {"type": "image_url", "image_url": {"url": TINY_PNG_DATA_URL}},
                    ],
                }
            ],
            max_tokens=16,
            temperature=0,
            extra_body=default_extra_body(vision_provider.model_id),
        )

        current_stage = "report"
        report_provider = await get_active_provider("report", session)
        await request_text_completion(
            report_provider,
            messages=[{"role": "user", "content": "请回复 ok。"}],
            temperature=0,
            max_tokens=16,
            timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        failure = classify_ai_failure(exc)
        latency_ms = int((time.perf_counter() - started) * 1000)
        message = "API 连接测试失败。"
        if failure.code == AnalysisErrorCode.AI_API_AUTH_ERROR:
            message = "API Key 验证失败，请检查当前激活供应商的 Key 是否正确。"
        elif failure.code == AnalysisErrorCode.AI_API_QUOTA_EXCEEDED:
            message = "API 额度不足，请检查当前账户余额或调用配额。"
        elif failure.code == AnalysisErrorCode.AI_API_TIMEOUT:
            message = "API 连接超时，可以稍后重试。"

        return ApiConnectionTestResponse(
            status="error",
            latency_ms=latency_ms,
            error_code=failure.code.value,
            message=message,
            failed_stage=current_stage,
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    return ApiConnectionTestResponse(status="ok", latency_ms=latency_ms)
