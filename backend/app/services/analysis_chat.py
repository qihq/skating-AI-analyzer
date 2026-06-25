from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, AnalysisChatMessage, AnalysisCorrection
from app.services.analysis_corrections import (
    AnalysisCorrectionError,
    build_effective_analysis_payload,
    create_analysis_correction,
    list_analysis_corrections,
)
from app.services.providers import ActiveProviderConfig, get_active_provider, get_provider_config_by_id, request_text_completion
from app.services.snowball import build_memory_context


ANALYSIS_CHAT_SYSTEM_PROMPT = (
    "你是花样滑冰视频复盘助手，面向家长和教练回答某一次已完成分析的追问。"
    "你只能基于系统提供的已保存分析证据回答，包括报告、用户 comments、动作识别、关键帧、"
    "partial semantic candidates、交叉验证和生物力学摘要。不要编造没有出现在证据里的视频细节。"
    "当动作识别、关键帧或证据之间有冲突时，必须明确说明不确定性，并指出哪些证据支持当前结论、"
    "哪些证据支持另一种可能。若用户要求重新看完整视频，说明当前聊天不会重新跑视频分析，"
    "可以建议重新分析或后续关键帧视觉复核。回答要简洁、具体、可执行。"
)
CORRECTION_SUGGESTION_PROMPT = (
    "\n\nCorrection proposal protocol: if the user explicitly asks to correct action labels, action confirmation, "
    "or keyframes, you may propose a correction, but never say it has been applied. The last line must be exactly "
    "CORRECTION_SUGGESTION_JSON={\"kind\":\"action_label|keyframes|report_note\",\"payload\":{...},\"rationale\":\"...\"}. "
    "Use action_label for action_type/action_subtype/action_confirmation, keyframes for T/A/L or semantic frame changes, "
    "and report_note only for a narrative note. If the conversation confirms a more accurate action type, action name, "
    "or T/A/L keyframes, output the marker with the best structured values so the UI can prefill a human-reviewed form. "
    "For action_label payloads, include action_type when known, action_subtype when known, and action_confirmation.confirmed_action "
    "for the action name. For keyframes payloads, include key_frames with T, A, and/or L values. If no concrete correction "
    "is requested or confirmed, omit this marker."
)
MODEL_IDENTITY_PROMPT = (
    "\n\nModel identity protocol: the actual model/provider for this request is supplied in the evidence JSON under "
    "request_model. If the user asks what model, provider, vendor, or AI identity is being used, answer only from "
    "request_model.name, request_model.provider, and request_model.model_id. Do not claim to be Claude, Anthropic, "
    "OpenAI, ChatGPT, or any other vendor/model unless request_model explicitly says so."
)

MAX_HISTORY_MESSAGES = 12
MAX_CONTEXT_CHARS = 12000


class AnalysisChatError(RuntimeError):
    pass


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _compact_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def _provider_identity_payload(provider: ActiveProviderConfig) -> dict[str, str]:
    return {
        "id": provider.id,
        "slot": provider.slot,
        "name": provider.name,
        "provider": provider.provider,
        "model_id": provider.model_id,
    }


def _is_model_identity_question(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.strip().lower())
    if not normalized:
        return False
    english_patterns = (
        "whatmodel",
        "whichmodel",
        "whatllm",
        "whichllm",
        "whatprovider",
        "whichprovider",
        "modelareyou",
        "whoareyou",
        "areyouclaude",
        "areyouchatgpt",
        "areyouopenai",
    )
    if any(pattern in normalized for pattern in english_patterns):
        return True
    chinese_patterns = (
        "什么模型",
        "哪个模型",
        "哪一个模型",
        "模型是什么",
        "当前模型",
        "现在模型",
        "用的模型",
        "使用的模型",
        "什么provider",
        "哪个provider",
        "什么供应商",
        "哪个供应商",
        "你是谁",
        "你是claude",
        "你是chatgpt",
    )
    return any(pattern in normalized for pattern in chinese_patterns)


def _model_identity_reply(provider: ActiveProviderConfig) -> str:
    label = provider.name or provider.model_id or provider.provider
    provider_name = provider.provider or "unknown"
    model_id = provider.model_id or "unknown"
    return (
        f"本次追问实际使用的是 **{label}**。\n\n"
        f"- Provider: `{provider_name}`\n"
        f"- Model ID: `{model_id}`\n\n"
        "如果页面上选择的是“默认模型”，它对应当前激活的 report 模型。"
    )


def _limit_list(value: Any, limit: int) -> list[Any]:
    return value[:limit] if isinstance(value, list) else []


def _extract_video_temporal_diagnostics(frame_motion_scores: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(frame_motion_scores, dict):
        return {}
    video_temporal = frame_motion_scores.get("video_temporal")
    resolved = frame_motion_scores.get("resolved_keyframes")
    if not isinstance(video_temporal, dict) and not isinstance(resolved, dict):
        return {}
    return {
        "action_confirmation": video_temporal.get("action_confirmation") if isinstance(video_temporal, dict) else None,
        "video_ai_confidence": video_temporal.get("confidence") if isinstance(video_temporal, dict) else None,
        "video_ai_provider": video_temporal.get("provider") if isinstance(video_temporal, dict) else None,
        "video_ai_model": video_temporal.get("model") if isinstance(video_temporal, dict) else None,
        "selected_semantic_frames": _limit_list(resolved.get("selected") if isinstance(resolved, dict) else None, 8),
        "partial_semantic_frames": _limit_list(resolved.get("partial_selected") if isinstance(resolved, dict) else None, 8),
        "resolved_confidence": resolved.get("confidence") if isinstance(resolved, dict) else None,
        "resolver_source": resolved.get("source") if isinstance(resolved, dict) else None,
        "quality_flags": resolved.get("quality_flags") if isinstance(resolved, dict) else [],
        "fallback_reason": (
            video_temporal.get("fallback_reason") or video_temporal.get("fallback_recommendation")
            if isinstance(video_temporal, dict)
            else None
        ),
    }


def _report_evidence(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    return {
        "summary": report.get("summary"),
        "issues": _limit_list(report.get("issues"), 8),
        "improvements": _limit_list(report.get("improvements"), 8),
        "training_focus": report.get("training_focus"),
        "subscores": report.get("subscores") if isinstance(report.get("subscores"), dict) else {},
        "data_quality": report.get("data_quality"),
        "user_note": report.get("user_note"),
        "user_note_response": report.get("user_note_response"),
        "action_confirmation": report.get("action_confirmation") if isinstance(report.get("action_confirmation"), dict) else None,
    }


def _vision_evidence(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "action_phase_summary": value.get("action_phase_summary"),
        "frame_analysis": _limit_list(value.get("frame_analysis"), 12),
        "model_results": _limit_list(value.get("model_results"), 4),
        "fusion_decisions": _limit_list(value.get("fusion_decisions"), 6),
        "data_quality_hint": value.get("data_quality_hint"),
        "quality_flags": value.get("quality_flags") if isinstance(value.get("quality_flags"), list) else [],
        "conflict_level": value.get("conflict_level"),
    }


def _cross_validation_evidence(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "recommended_path": value.get("recommended_path"),
        "conflict_level": value.get("conflict_level"),
        "downgraded_reasons": value.get("downgraded_reasons") if isinstance(value.get("downgraded_reasons"), list) else [],
        "fusion_diagnostics": value.get("fusion_diagnostics") if isinstance(value.get("fusion_diagnostics"), dict) else {},
        "path_b_evidence": value.get("path_b_evidence") if isinstance(value.get("path_b_evidence"), dict) else {},
        "auto_eval": value.get("auto_eval") if isinstance(value.get("auto_eval"), dict) else {},
    }


def _bio_evidence(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "key_frames": value.get("key_frames") if isinstance(value.get("key_frames"), dict) else {},
        "key_frame_candidates": value.get("key_frame_candidates") if isinstance(value.get("key_frame_candidates"), dict) else {},
        "jump_metrics": value.get("jump_metrics") if isinstance(value.get("jump_metrics"), dict) else {},
        "jump_metrics_status": value.get("jump_metrics_status"),
        "jump_metrics_warning": value.get("jump_metrics_warning"),
        "bio_subscores": value.get("bio_subscores") if isinstance(value.get("bio_subscores"), dict) else {},
        "quality_flags": value.get("quality_flags") if isinstance(value.get("quality_flags"), list) else [],
    }


def build_analysis_chat_context(
    analysis: Analysis,
    *,
    memory_context: str = "",
    corrections: list[AnalysisCorrection] | None = None,
) -> dict[str, Any]:
    report = analysis.report if isinstance(analysis.report, dict) else None
    effective = build_effective_analysis_payload(analysis, corrections)
    effective_analysis = effective.get("analysis") if isinstance(effective.get("analysis"), dict) else {}
    effective_report = effective.get("report") if isinstance(effective.get("report"), dict) else {}
    effective_bio = effective.get("bio_data") if isinstance(effective.get("bio_data"), dict) else {}
    effective_motion = effective.get("frame_motion_scores") if isinstance(effective.get("frame_motion_scores"), dict) else {}
    context = {
        "analysis": {
            "id": analysis.id,
            "action_type": analysis.action_type,
            "action_subtype": analysis.action_subtype,
            "skill_category": analysis.skill_category,
            "analysis_profile": analysis.analysis_profile,
            "status": analysis.status,
            "force_score": analysis.force_score,
            "pipeline_version": analysis.pipeline_version,
            "created_at": analysis.created_at,
            "user_comments": analysis.note,
        },
        "effective_analysis": {
            "action_type": effective_analysis.get("action_type"),
            "action_subtype": effective_analysis.get("action_subtype"),
            "analysis_profile": effective_analysis.get("analysis_profile"),
            "force_score": effective_analysis.get("force_score"),
            "has_applied_corrections": bool(effective.get("has_applied_corrections")),
            "applied_corrections": effective_analysis.get("corrections_applied") or [],
        },
        "report": _report_evidence(report),
        "effective_report": _report_evidence(effective_report),
        "video_temporal_diagnostics": _extract_video_temporal_diagnostics(
            analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
        ),
        "effective_video_temporal_diagnostics": _extract_video_temporal_diagnostics(effective_motion),
        "vision_structured": _vision_evidence(analysis.vision_structured if isinstance(analysis.vision_structured, dict) else None),
        "vision_path_b": _vision_evidence(analysis.vision_path_b if isinstance(analysis.vision_path_b, dict) else None),
        "cross_validation": _cross_validation_evidence(analysis.cross_validation if isinstance(analysis.cross_validation, dict) else None),
        "bio_data": _bio_evidence(analysis.bio_data if isinstance(analysis.bio_data, dict) else None),
        "effective_bio_data": _bio_evidence(effective_bio),
        "corrections": effective.get("corrections") or [],
    }
    if _clean_text(memory_context):
        context["skater_memory"] = memory_context
    return context


def render_analysis_chat_context(context: dict[str, Any]) -> str:
    text = _compact_json(context)
    if len(text) <= MAX_CONTEXT_CHARS:
        return text
    return text[:MAX_CONTEXT_CHARS] + "\n...[context truncated]"


def serialize_chat_message(message: AnalysisChatMessage) -> dict[str, Any]:
    snapshot = message.context_snapshot if isinstance(message.context_snapshot, dict) else {}
    provider = snapshot.get("provider") if isinstance(snapshot.get("provider"), dict) else {}
    return {
        "id": message.id,
        "analysis_id": message.analysis_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "provider_id": provider.get("id") if message.role == "assistant" else None,
        "provider_name": provider.get("name") if message.role == "assistant" else None,
        "model_id": provider.get("model_id") if message.role == "assistant" else None,
    }


async def list_analysis_chat_messages(session: AsyncSession, analysis_id: str) -> list[AnalysisChatMessage]:
    result = await session.execute(
        select(AnalysisChatMessage)
        .where(AnalysisChatMessage.analysis_id == analysis_id)
        .order_by(AnalysisChatMessage.created_at.asc(), AnalysisChatMessage.id.asc())
    )
    return list(result.scalars().all())


def _extract_correction_suggestion(text: str) -> tuple[str, dict[str, Any] | None]:
    marker = "CORRECTION_SUGGESTION_JSON="
    if marker not in text:
        return text, None
    before, after = text.split(marker, 1)
    json_text = after.strip().splitlines()[0].strip()
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return re.sub(r"\n?CORRECTION_SUGGESTION_JSON=.*", "", text, flags=re.DOTALL).rstrip(), None
    if not isinstance(payload, dict):
        return before.rstrip(), None
    return before.rstrip(), payload


def _fallback_text_for_correction_suggestion(suggestion: dict[str, Any] | None) -> str:
    kind = suggestion.get("kind") if isinstance(suggestion, dict) else None
    if kind == "action_label":
        return "我已根据这轮追问生成动作类型/动作名称的待确认草稿。请在右侧 form 里核对，确认后再应用到当前系统数据。"
    if kind == "keyframes":
        return "我已根据这轮追问生成 T/A/L 关键帧的待确认草稿。请在右侧 form 里核对，确认后再应用到当前系统数据。"
    if kind == "report_note":
        return "我已根据这轮追问生成报告说明的待确认草稿。请先核对，确认后再应用。"
    return ""


async def _maybe_create_correction_suggestion(
    session: AsyncSession,
    analysis: Analysis,
    suggestion: dict[str, Any] | None,
) -> None:
    if not suggestion:
        return
    kind = suggestion.get("kind")
    payload = suggestion.get("payload")
    if not isinstance(kind, str) or not isinstance(payload, dict):
        return
    try:
        await create_analysis_correction(
            session,
            analysis,
            kind=kind,
            payload=payload,
            rationale=_clean_text(suggestion.get("rationale")) or None,
            source="chat_suggestion",
            status="proposed",
        )
    except AnalysisCorrectionError:
        return


async def _resolve_chat_provider(
    session: AsyncSession,
    provider_id: str | None,
) -> ActiveProviderConfig:
    selected_id = _clean_text(provider_id)
    if not selected_id:
        return await get_active_provider("report", session)
    try:
        return await get_provider_config_by_id(selected_id, slot="report", session=session)
    except ValueError as exc:
        raise AnalysisChatError("追问回复模型必须选择 report 类型的供应商。") from exc


async def create_analysis_chat_reply(
    session: AsyncSession,
    analysis: Analysis,
    *,
    message: str,
    provider_id: str | None = None,
) -> tuple[AnalysisChatMessage, list[AnalysisChatMessage]]:
    user_text = message.strip()
    if not user_text:
        raise AnalysisChatError("追问内容不能为空。")
    if analysis.status != "completed":
        raise AnalysisChatError("只有 completed 状态的分析才能继续追问。")
    if not isinstance(analysis.report, dict) and not isinstance(analysis.vision_structured, dict):
        raise AnalysisChatError("当前分析缺少可用于追问的结构化证据。")

    previous = await list_analysis_chat_messages(session, analysis.id)
    corrections = await list_analysis_corrections(session, analysis.id)
    memory_context = await build_memory_context(analysis.skater_id, session)
    context = build_analysis_chat_context(analysis, memory_context=memory_context, corrections=corrections)
    provider = await _resolve_chat_provider(session, provider_id)
    provider_identity = _provider_identity_payload(provider)
    context = {"request_model": provider_identity, **context}
    context_snapshot = json.loads(_compact_json(context))
    context_snapshot["provider"] = provider_identity
    context_text = render_analysis_chat_context(context)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": ANALYSIS_CHAT_SYSTEM_PROMPT + CORRECTION_SUGGESTION_PROMPT + MODEL_IDENTITY_PROMPT,
        },
        {"role": "user", "content": f"以下是这条视频分析的已保存证据 JSON：\n{context_text}"},
    ]
    for item in previous[-MAX_HISTORY_MESSAGES:]:
        if item.role in {"user", "assistant"} and item.content.strip():
            messages.append({"role": item.role, "content": item.content.strip()})
    messages.append({"role": "user", "content": user_text})

    if _is_model_identity_question(user_text):
        reply = _model_identity_reply(provider)
    else:
        reply = await request_text_completion(
            provider,
            messages=messages,
            temperature=0.35,
            max_tokens=900,
        )
    assistant_text, correction_suggestion = _extract_correction_suggestion((reply or "").strip())
    if not assistant_text:
        assistant_text = _fallback_text_for_correction_suggestion(correction_suggestion)
    if not assistant_text:
        assistant_text = "我暂时没有拿到稳定回复。可以换一种问法，或先重新生成报告后再追问。"

    user_created_at = datetime.now(timezone.utc)
    assistant_created_at = user_created_at + timedelta(microseconds=1)
    user_message = AnalysisChatMessage(
        id=str(uuid4()),
        analysis_id=analysis.id,
        role="user",
        content=user_text,
        context_snapshot=None,
        created_at=user_created_at,
    )
    assistant_message = AnalysisChatMessage(
        id=str(uuid4()),
        analysis_id=analysis.id,
        role="assistant",
        content=assistant_text,
        context_snapshot=context_snapshot,
        created_at=assistant_created_at,
    )
    session.add(user_message)
    session.add(assistant_message)
    await session.commit()
    await session.refresh(user_message)
    await session.refresh(assistant_message)
    await _maybe_create_correction_suggestion(session, analysis, correction_suggestion)
    return assistant_message, await list_analysis_chat_messages(session, analysis.id)
