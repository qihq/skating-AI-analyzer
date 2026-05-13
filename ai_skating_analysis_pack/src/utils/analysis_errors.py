from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import httpx

try:
    from openai import APITimeoutError, AuthenticationError, BadRequestError, PermissionDeniedError, RateLimitError
except Exception:  # noqa: BLE001
    class APITimeoutError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class BadRequestError(Exception):
        pass

    class PermissionDeniedError(Exception):
        pass

    class RateLimitError(Exception):
        pass


class AnalysisErrorCode(str, Enum):
    VIDEO_DECODE_FAILED = "VIDEO_DECODE_FAILED"
    FRAME_EXTRACT_FAILED = "FRAME_EXTRACT_FAILED"
    AI_API_TIMEOUT = "AI_API_TIMEOUT"
    AI_API_AUTH_ERROR = "AI_API_AUTH_ERROR"
    AI_API_QUOTA_EXCEEDED = "AI_API_QUOTA_EXCEEDED"
    AI_API_CONTENT_FILTER = "AI_API_CONTENT_FILTER"
    AI_RESPONSE_PARSE_FAIL = "AI_RESPONSE_PARSE_FAIL"
    REPORT_SAVE_FAILED = "REPORT_SAVE_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


ERROR_TITLES: dict[AnalysisErrorCode, str] = {
    AnalysisErrorCode.VIDEO_DECODE_FAILED: "视频格式无法识别",
    AnalysisErrorCode.FRAME_EXTRACT_FAILED: "视频帧提取失败",
    AnalysisErrorCode.AI_API_TIMEOUT: "AI 分析超时",
    AnalysisErrorCode.AI_API_AUTH_ERROR: "API Key 验证失败",
    AnalysisErrorCode.AI_API_QUOTA_EXCEEDED: "API 额度不足",
    AnalysisErrorCode.AI_API_CONTENT_FILTER: "内容被 AI 安全过滤",
    AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL: "AI 返回格式异常",
    AnalysisErrorCode.REPORT_SAVE_FAILED: "报告保存失败",
    AnalysisErrorCode.UNKNOWN_ERROR: "未知错误",
}


@dataclass(slots=True)
class AnalysisFailure:
    code: AnalysisErrorCode
    detail: str


class AnalysisPipelineError(Exception):
    def __init__(self, code: AnalysisErrorCode, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def friendly_error_title(code: AnalysisErrorCode | str | None) -> str:
    if not code:
        return ERROR_TITLES[AnalysisErrorCode.UNKNOWN_ERROR]
    normalized = code if isinstance(code, AnalysisErrorCode) else AnalysisErrorCode(code)
    return ERROR_TITLES.get(normalized, ERROR_TITLES[AnalysisErrorCode.UNKNOWN_ERROR])


def stringify_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    if detail:
        return detail
    return exc.__class__.__name__


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _extract_error_text(exc: Exception) -> str:
    parts = [stringify_exception(exc)]

    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(str(body))

    response = getattr(exc, "response", None)
    response_text = getattr(response, "text", None)
    if isinstance(response_text, str) and response_text.strip():
        parts.append(response_text.strip())

    return " ".join(part for part in parts if part).lower()


def classify_video_failure(exc: Exception) -> AnalysisFailure:
    detail = stringify_exception(exc)
    lowered = detail.lower()
    decode_tokens = (
        "invalid data found when processing input",
        "moov atom not found",
        "could not find codec parameters",
        "error while decoding",
        "unsupported codec",
        "could not open input file",
        "input/output error",
    )
    code = (
        AnalysisErrorCode.VIDEO_DECODE_FAILED
        if any(token in lowered for token in decode_tokens)
        else AnalysisErrorCode.FRAME_EXTRACT_FAILED
    )
    return AnalysisFailure(code=code, detail=detail)


def classify_ai_failure(exc: Exception) -> AnalysisFailure:
    if isinstance(exc, AnalysisPipelineError):
        return AnalysisFailure(code=exc.code, detail=exc.detail)

    detail = stringify_exception(exc)
    lowered = _extract_error_text(exc)
    status_code = _extract_status_code(exc)

    if isinstance(exc, (APITimeoutError, httpx.TimeoutException)) or "timeout" in lowered:
        code = AnalysisErrorCode.AI_API_TIMEOUT
    elif isinstance(exc, (AuthenticationError, PermissionDeniedError)) or status_code in {401, 403}:
        code = AnalysisErrorCode.AI_API_AUTH_ERROR
    elif isinstance(exc, RateLimitError) or status_code == 429:
        code = AnalysisErrorCode.AI_API_QUOTA_EXCEEDED
    elif isinstance(exc, BadRequestError) and any(token in lowered for token in ("content_filter", "content filter", "safety", "审核")):
        code = AnalysisErrorCode.AI_API_CONTENT_FILTER
    elif any(token in lowered for token in ("content_filter", "content filter", "safety system", "safety policy", "审核拦截")):
        code = AnalysisErrorCode.AI_API_CONTENT_FILTER
    elif any(token in lowered for token in ("api key", "api_key", "secret_key", "尚未配置 api key", "未找到 slot", "尚未配置")):
        code = AnalysisErrorCode.AI_API_AUTH_ERROR
    else:
        code = AnalysisErrorCode.UNKNOWN_ERROR

    return AnalysisFailure(code=code, detail=detail)
