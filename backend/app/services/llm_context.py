from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.services.snowball import build_memory_context


@dataclass(slots=True)
class AnalysisPromptContext:
    action_type: str
    action_subtype: str | None
    skill_category: str | None
    analysis_profile: str | None
    profile_evidence: dict[str, Any] | None
    motion_features: dict[str, Any] | None
    bio_data: dict[str, Any] | None
    user_note: str | None
    memory_context: str


def _clean_text(value: str | None) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _json_compact(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def render_prompt_context(context: AnalysisPromptContext, *, include_bio: bool = False) -> str:
    subtype = _clean_text(context.action_subtype)
    skill_category = _clean_text(context.skill_category)
    lines = [
        "---",
        "统一分析上下文（必须遵守）:",
        f"action_type: {context.action_type}",
        f"action_subtype: {subtype or '未指定'}",
        f"skill_category: {skill_category or '未指定'}",
        f"analysis_profile: {_clean_text(context.analysis_profile) or 'unknown'}",
        f"profile_evidence: {_json_compact(context.profile_evidence)}",
        f"motion_features: {_json_compact(context.motion_features)}",
        "上下文规则:",
        "- action_type 是用户给的大类提示；action_subtype/skill_category 若为未指定，表示用户不确定细项，不能强行猜成具体动作名。",
        "- profile_evidence、motion_features、bio_data 是后端证据；与画面不一致时必须降低置信度并说明不确定。",
        "- 上传备注/comments 是用户观察线索，不等同于已验证事实；只有视频或结构化证据支持时才能写成结论。",
    ]
    if include_bio:
        lines.append(f"bio_data: {_json_compact(context.bio_data)}")
    note = _clean_text(context.user_note)
    if note:
        lines.append(f"上传备注/额外 comments: {note}")
    memory = _clean_text(context.memory_context)
    if memory:
        lines.extend(["IceBuddy 长期记忆:", memory])
    lines.append("---")
    return "\n".join(lines)


async def build_analysis_prompt_context(
    *,
    action_type: str,
    action_subtype: str | None,
    skill_category: str | None,
    analysis_profile: str | None,
    profile_evidence: dict[str, Any] | None,
    motion_features: dict[str, Any] | None,
    bio_data: dict[str, Any] | None,
    skater_id: str | None,
    user_note: str | None,
) -> AnalysisPromptContext:
    return AnalysisPromptContext(
        action_type=action_type,
        action_subtype=action_subtype,
        skill_category=skill_category,
        analysis_profile=analysis_profile,
        profile_evidence=profile_evidence,
        motion_features=motion_features,
        bio_data=bio_data,
        user_note=user_note,
        memory_context=await build_memory_context(skater_id),
    )
