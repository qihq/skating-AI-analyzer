from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.fact_consumers import (
    apply_artifact_metadata,
    artifact_reference,
    consumer_for_analysis,
    family_safe_fact_payload,
    generation_fingerprint,
)
from app.models import Analysis, AnalysisChatMessage, AnalysisCorrection
from app.services.llm_context import split_user_note_questions
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
    "先直接回答用户问的技术问题，再给证据和建议；不要复述用户问题或 saved comments，"
    "不要使用‘能确认的是/不能确认的是’‘已纳入关注’等固定模板。证据不足时只用一句话说明缺少哪种画面或阶段。"
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
MULTI_QUESTION_PROMPT = (
    "\n\nComment question protocol: if saved user comments or the latest user message contain multiple questions, "
    "answer each one explicitly with a short numbered list. Lead with the actual technical judgment, cite the most "
    "relevant saved evidence, and give one concrete next check or drill. Do not repeat a generic confirmed/unconfirmed format."
)

MAX_HISTORY_MESSAGES = 12
MAX_CONTEXT_CHARS = 12000
FULL_VIDEO_REANALYSIS_ACTION = {
    "kind": "full_video_reanalysis",
    "label": "完整重新分析",
    "reset_target_lock": True,
}
VIDEO_AI_KEYFRAME_RERUN_ACTION = {
    "kind": "video_ai_keyframe_rerun",
    "label": "视频 AI 重识别关键帧",
}


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


def _is_full_video_reanalysis_request(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.strip().lower())
    if not normalized:
        return False
    chinese_needles = (
        "重新识别关键帧",
        "重识别关键帧",
        "重新跑关键帧",
        "重跑关键帧",
        "重新分析关键帧",
        "重新看完整视频",
        "重新看一遍完整视频",
        "重新用完整视频",
        "用完整视频跑分析",
        "完整视频跑分析",
        "完整重新分析",
        "重新完整分析",
        "完整重跑",
        "重新跑完整视频",
    )
    if any(needle in normalized for needle in chinese_needles):
        return True
    english_needles = (
        "rerunkeyframes",
        "re-detectkeyframes",
        "redetectkeyframes",
        "reanalyzefullvideo",
        "rerunfullvideo",
        "fullreanalysis",
        "fullvideoanalysis",
    )
    return any(needle in normalized for needle in english_needles)


def _is_video_ai_keyframe_rerun_request(text: str) -> bool:
    normalized = re.sub(r"[\s，,。.!！?？、；;：:]+", "", text.strip().lower())
    if not normalized:
        return False
    chinese_needles = (
        "只用视频ai重新识别关键帧",
        "只用视频ai重识别关键帧",
        "视频ai重新识别关键帧",
        "视频ai重识别关键帧",
        "视频ai重新跑关键帧",
        "视频ai重跑关键帧",
        "只跑全量视频关键帧",
        "只重跑全量视频关键帧",
        "只重跑视频关键帧",
        "只重新识别关键帧",
        "不要重跑主人物只重跑全量视频关键帧",
        "不要重跑主人物只重新识别关键帧",
        "不重跑主人物只重跑关键帧",
        "不重跑主人物只重新识别关键帧",
        "不重跑主人物追踪只重跑关键帧",
        "不重跑主人物追踪只重新识别关键帧",
    )
    if any(needle in normalized for needle in chinese_needles):
        return True
    english_needles = (
        "videoairerunkeyframes",
        "videoaire-detectkeyframes",
        "videoairedetectkeyframes",
        "rerunkeyframesvideoai",
        "redetectkeyframesvideoai",
        "keyframesonlyrerun",
        "keyframe-onlyrerun",
        "onlyrerunkeyframes",
        "donotreruntargetlock",
        "withouttargetlock",
    )
    return any(needle in normalized for needle in english_needles)


def _full_video_reanalysis_reply() -> str:
    return (
        "当前追问只会基于已经保存的分析证据回答，不会重新看完整视频或重新识别关键帧。\n\n"
        "如果你要重新识别关键帧，需要用原视频重新跑一次完整分析。这个过程会从主人物定位开始重新识别，"
        "不复用当前的主人物锁定；同时会消耗一次 AI 调用额度，并在完成后覆盖当前报告。\n\n"
        "我已为你准备好“完整重新分析”的确认操作。确认后系统会重新定位主人物并重新分析关键帧。"
    )


def _video_ai_keyframe_rerun_reply() -> str:
    return (
        "可以，只让视频 AI 重新看完整原视频来定位 T/A/L 关键帧。\n\n"
        "这个操作不会重跑主人物追踪、pose、生物力学或 Path A/B 报告，也不会自动覆盖当前报告。"
        "系统会生成一张“关键帧修正卡”，你确认应用后才会进入有效数据层；如果之后要更新文字或分数，再用现有的“从修正重新生成报告”。"
    )


def _limit_list(value: Any, limit: int) -> list[Any]:
    return value[:limit] if isinstance(value, list) else []


def build_analysis_chat_context(
    analysis: Analysis,
    *,
    memory_context: str = "",
    corrections: list[AnalysisCorrection] | None = None,
    selected_event_id: str | None = None,
) -> dict[str, Any]:
    all_facts = consumer_for_analysis(analysis, "family_display")
    # Chat must be able to explain uncertainty/conflict/unobservable coverage
    # from the same authority.  The payload remains bounded semantic facts;
    # it never includes raw Path A/B, pose, or biomechanics dictionaries.
    safe_payload = family_safe_fact_payload(all_facts, include_noneligible=True)
    if selected_event_id:
        safe_payload["facts"] = [
            fact
            for fact in safe_payload["facts"]
            if fact.get("event_id") in {None, selected_event_id}
        ]
    context = {
        "selection": {
            "event_id": selected_event_id,
            "scope": "event" if selected_event_id else "whole_analysis",
        },
        "analysis_facts": safe_payload,
        "correction_history": [
            {
                "id": item.id,
                "event_id": getattr(item, "event_id", None),
                "kind": item.kind,
                "status": item.status,
                "source": item.source,
                "rationale": item.rationale,
            }
            for item in (corrections or [])
        ],
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
        "selected_event_id": message.selected_event_id,
        "facts_authority": message.facts_authority,
        "source_fact_hash": message.source_fact_hash,
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
    selected_event_id: str | None = None,
) -> tuple[AnalysisChatMessage, list[AnalysisChatMessage], dict[str, Any] | None]:
    user_text = message.strip()
    if not user_text:
        raise AnalysisChatError("追问内容不能为空。")
    if analysis.status != "completed":
        raise AnalysisChatError("只有 completed 状态的分析才能继续追问。")
    consumer = consumer_for_analysis(analysis, "family_display")
    if not consumer.facts:
        raise AnalysisChatError("当前分析缺少可用于追问的结构化证据。")

    previous = await list_analysis_chat_messages(session, analysis.id)
    corrections = await list_analysis_corrections(session, analysis.id)
    memory_context = await build_memory_context(analysis.skater_id, session)
    context = build_analysis_chat_context(
        analysis,
        memory_context=memory_context,
        corrections=corrections,
        selected_event_id=selected_event_id,
    )
    provider = await _resolve_chat_provider(session, provider_id)
    provider_identity = _provider_identity_payload(provider)
    context = {"request_model": provider_identity, **context}
    context_snapshot = json.loads(_compact_json(context))
    context_snapshot["provider"] = provider_identity
    context_text = render_analysis_chat_context(context)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": ANALYSIS_CHAT_SYSTEM_PROMPT + CORRECTION_SUGGESTION_PROMPT + MODEL_IDENTITY_PROMPT + MULTI_QUESTION_PROMPT,
        },
        {"role": "user", "content": f"以下是这条视频分析的已保存证据 JSON：\n{context_text}"},
    ]
    for item in previous[-MAX_HISTORY_MESSAGES:]:
        if item.role in {"user", "assistant"} and item.content.strip():
            messages.append({"role": item.role, "content": item.content.strip()})
    messages.append({"role": "user", "content": user_text})

    suggested_action: dict[str, Any] | None = None
    if _is_video_ai_keyframe_rerun_request(user_text):
        reply = _video_ai_keyframe_rerun_reply()
        suggested_action = dict(VIDEO_AI_KEYFRAME_RERUN_ACTION)
    elif _is_full_video_reanalysis_request(user_text):
        reply = _full_video_reanalysis_reply()
        suggested_action = dict(FULL_VIDEO_REANALYSIS_ACTION)
    elif _is_model_identity_question(user_text):
        reply = _model_identity_reply(provider)
    else:
        reply = await request_text_completion(
            provider,
            messages=messages,
            temperature=0.35,
            max_tokens=1800,
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
        selected_event_id=selected_event_id,
        created_at=user_created_at,
    )
    assistant_message = AnalysisChatMessage(
        id=str(uuid4()),
        analysis_id=analysis.id,
        role="assistant",
        content=assistant_text,
        context_snapshot=context_snapshot,
        selected_event_id=selected_event_id,
        created_at=assistant_created_at,
    )
    generation = generation_fingerprint(
        artifact_type="analysis_chat_message",
        source_fact_hash=consumer.source_fact_hash,
        provider=provider.provider,
        model=provider.model_id,
        prompt_version="analysis-chat.v2",
        extra={"selected_event_id": selected_event_id or "whole_analysis"},
    )
    reference = artifact_reference(consumer, artifact_type="analysis_chat_message", generation=generation)
    apply_artifact_metadata(user_message, reference)
    apply_artifact_metadata(assistant_message, reference)
    session.add(user_message)
    session.add(assistant_message)
    await session.commit()
    await session.refresh(user_message)
    await session.refresh(assistant_message)
    await _maybe_create_correction_suggestion(session, analysis, correction_suggestion)
    return assistant_message, await list_analysis_chat_messages(session, analysis.id), suggested_action
