from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, AnalysisCorrection


VALID_CORRECTION_KINDS = {"action_label", "keyframes", "report_note", "report_regeneration", "target_lock"}
VALID_CORRECTION_SOURCES = {"manual", "chat_suggestion", "video_ai_keyframe_rerun"}
VALID_CORRECTION_STATUSES = {"proposed", "applied", "dismissed"}
KEYFRAME_KEYS = ("T", "A", "L")


class AnalysisCorrectionError(ValueError):
    pass


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _deepcopy_dict(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _limit_text(value: Any, limit: int = 2000) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    return text[:limit]


def normalize_correction_kind(value: str) -> str:
    kind = str(value or "").strip().lower()
    if kind not in VALID_CORRECTION_KINDS:
        raise AnalysisCorrectionError("Unsupported correction kind.")
    return kind


def normalize_correction_source(value: str | None) -> str:
    source = str(value or "manual").strip().lower()
    if source not in VALID_CORRECTION_SOURCES:
        raise AnalysisCorrectionError("Unsupported correction source.")
    return source


def normalize_correction_status(value: str | None) -> str:
    status = str(value or "proposed").strip().lower()
    if status not in VALID_CORRECTION_STATUSES:
        raise AnalysisCorrectionError("Unsupported correction status.")
    return status


def _normalize_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in ("action_type", "action_subtype", "analysis_profile"):
        value = _clean_text(payload.get(key))
        if value is not None:
            normalized[key] = value

    confirmation = payload.get("action_confirmation")
    if isinstance(confirmation, dict):
        normalized["action_confirmation"] = {
            key: value
            for key, value in confirmation.items()
            if value not in (None, "", [], {})
        }
    else:
        confirmed_action = _clean_text(payload.get("confirmed_action"))
        jump_type = _clean_text(payload.get("jump_type"))
        action_family = _clean_text(payload.get("action_family"))
        confidence = payload.get("confidence")
        notes = _limit_text(payload.get("notes"), 800)
        if any(value is not None for value in (confirmed_action, jump_type, action_family, confidence, notes)):
            normalized["action_confirmation"] = {
                "confirmed_action": confirmed_action,
                "jump_type": jump_type,
                "action_family": action_family,
                "confidence": confidence,
                "notes": notes,
            }
    if not normalized:
        raise AnalysisCorrectionError("Action correction requires at least one action field.")
    return normalized


def _normalize_keyframe_value(value: Any) -> Any:
    if isinstance(value, dict):
        frame_id = _clean_text(value.get("frame_id")) or _clean_text(value.get("frame"))
        timestamp = value.get("timestamp")
        normalized: dict[str, Any] = {key: item for key, item in value.items() if item not in (None, "", [], {})}
        if frame_id is not None:
            normalized["frame_id"] = frame_id
        if timestamp is not None:
            normalized["timestamp"] = timestamp
        return normalized
    return _clean_text(value)


def _normalize_keyframes_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_frames = payload.get("key_frames")
    if not isinstance(raw_frames, dict):
        raw_frames = {
            key: payload.get(key)
            for key in KEYFRAME_KEYS
            if payload.get(key) not in (None, "", [], {})
        }

    key_frames: dict[str, Any] = {}
    for key in KEYFRAME_KEYS:
        if key not in raw_frames:
            continue
        normalized = _normalize_keyframe_value(raw_frames.get(key))
        if normalized not in (None, "", {}, []):
            key_frames[key] = normalized

    selected = payload.get("selected_semantic_frames")
    partial_promotions = payload.get("partial_semantic_promotions")
    normalized: dict[str, Any] = {}
    if key_frames:
        normalized["key_frames"] = key_frames
    if isinstance(selected, list):
        normalized["selected_semantic_frames"] = [item for item in selected if isinstance(item, dict)]
    if isinstance(partial_promotions, list):
        normalized["partial_semantic_promotions"] = [item for item in partial_promotions if isinstance(item, dict)]
    source = _clean_text(payload.get("source"))
    if source is not None:
        normalized["source"] = source
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, dict):
        normalized["diagnostics"] = diagnostics
    if not normalized:
        raise AnalysisCorrectionError("Keyframe correction requires key_frames or semantic frame selections.")
    return normalized


def _normalize_report_note_payload(payload: dict[str, Any]) -> dict[str, Any]:
    note = _limit_text(payload.get("note") or payload.get("user_note_response") or payload.get("summary_note"))
    if note is None:
        raise AnalysisCorrectionError("Report-note correction requires note.")
    return {"note": note}


def _normalize_report_regeneration_payload(payload: dict[str, Any]) -> dict[str, Any]:
    report = payload.get("report")
    if not isinstance(report, dict):
        raise AnalysisCorrectionError("Report-regeneration correction requires report.")
    normalized: dict[str, Any] = {"report": report}
    if "force_score" in payload:
        normalized["force_score"] = payload.get("force_score")
    generated_at = _clean_text(payload.get("generated_at"))
    if generated_at:
        normalized["generated_at"] = generated_at
    return normalized


def _normalize_target_lock_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in payload.items() if value not in (None, "", [], {})}
    if not normalized:
        raise AnalysisCorrectionError("Target-lock correction payload cannot be empty.")
    return normalized


def normalize_correction_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AnalysisCorrectionError("Correction payload must be an object.")
    if kind == "action_label":
        return _normalize_action_payload(payload)
    if kind == "keyframes":
        return _normalize_keyframes_payload(payload)
    if kind == "report_note":
        return _normalize_report_note_payload(payload)
    if kind == "report_regeneration":
        return _normalize_report_regeneration_payload(payload)
    if kind == "target_lock":
        return _normalize_target_lock_payload(payload)
    raise AnalysisCorrectionError("Unsupported correction kind.")


def _snapshot_for_kind(analysis: Analysis, kind: str) -> dict[str, Any]:
    report = analysis.report if isinstance(analysis.report, dict) else {}
    bio_data = analysis.bio_data if isinstance(analysis.bio_data, dict) else {}
    motion = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else {}
    resolved = motion.get("resolved_keyframes") if isinstance(motion.get("resolved_keyframes"), dict) else {}
    if kind == "action_label":
        return {
            "action_type": analysis.action_type,
            "action_subtype": analysis.action_subtype,
            "analysis_profile": analysis.analysis_profile,
            "report_action_confirmation": report.get("action_confirmation"),
            "video_temporal_action_confirmation": (
                motion.get("video_temporal", {}).get("action_confirmation")
                if isinstance(motion.get("video_temporal"), dict)
                else None
            ),
        }
    if kind == "keyframes":
        return {
            "bio_key_frames": bio_data.get("key_frames"),
            "selected_semantic_frames": resolved.get("selected"),
            "partial_semantic_frames": resolved.get("partial_selected"),
            "resolved_source": resolved.get("source"),
        }
    if kind == "report_note":
        return {
            "report_user_note_response": report.get("user_note_response"),
            "report_summary": report.get("summary"),
        }
    if kind == "report_regeneration":
        return {
            "report": report,
            "force_score": analysis.force_score,
        }
    if kind == "target_lock":
        return {
            "target_lock": analysis.target_lock,
            "target_lock_status": analysis.target_lock_status,
        }
    return {}


def _merge_action_correction(effective: dict[str, Any], payload: dict[str, Any]) -> None:
    analysis = effective["analysis"]
    report = effective["report"]
    motion = effective["frame_motion_scores"]
    for key in ("action_type", "action_subtype", "analysis_profile"):
        if key in payload:
            analysis[key] = payload[key]
    confirmation = payload.get("action_confirmation")
    if isinstance(confirmation, dict):
        report["action_confirmation"] = {
            **(report.get("action_confirmation") if isinstance(report.get("action_confirmation"), dict) else {}),
            **confirmation,
            "corrected": True,
        }
        video_temporal = motion.setdefault("video_temporal", {})
        if isinstance(video_temporal, dict):
            video_temporal["action_confirmation"] = {
                **(video_temporal.get("action_confirmation") if isinstance(video_temporal.get("action_confirmation"), dict) else {}),
                **confirmation,
                "corrected": True,
            }


def _frame_to_bio_value(value: Any) -> str:
    if isinstance(value, dict):
        frame_id = _clean_text(value.get("frame_id")) or _clean_text(value.get("frame"))
        timestamp = value.get("timestamp")
        if frame_id:
            return frame_id
        if timestamp is not None:
            return str(timestamp)
        return str(value)
    return str(value)


def _merge_keyframe_correction(effective: dict[str, Any], payload: dict[str, Any]) -> None:
    bio_data = effective["bio_data"]
    motion = effective["frame_motion_scores"]
    resolved = motion.setdefault("resolved_keyframes", {})
    key_frames = payload.get("key_frames")
    if isinstance(key_frames, dict):
        bio_key_frames = dict(bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {})
        corrected_records = dict(bio_data.get("corrected_key_frames") if isinstance(bio_data.get("corrected_key_frames"), dict) else {})
        selected_by_key: dict[str, dict[str, Any]] = {}
        for key, value in key_frames.items():
            if key not in KEYFRAME_KEYS:
                continue
            bio_key_frames[key] = _frame_to_bio_value(value)
            corrected_records[key] = value
            if isinstance(value, dict):
                selected_by_key[key] = {
                    **value,
                    "phase_code": str(value.get("phase_code") or key),
                    "key_moment": str(value.get("key_moment") or key),
                    "selection_status": "applied_correction",
                    "correction_applied": True,
                }
        bio_data["key_frames"] = bio_key_frames
        bio_data["corrected_key_frames"] = corrected_records

        selected = resolved.get("selected") if isinstance(resolved.get("selected"), list) else []
        next_selected: list[dict[str, Any]] = []
        replaced: set[str] = set()
        for item in selected:
            if not isinstance(item, dict):
                continue
            key = _semantic_key(item)
            if key in selected_by_key:
                next_selected.append(selected_by_key[key])
                replaced.add(key)
            else:
                next_selected.append(item)
        for key in KEYFRAME_KEYS:
            if key in selected_by_key and key not in replaced:
                next_selected.append(selected_by_key[key])
        if next_selected:
            resolved["selected"] = next_selected

    selected = payload.get("selected_semantic_frames")
    if isinstance(selected, list) and selected:
        resolved["selected"] = [
            {**item, "selection_status": "applied_correction", "correction_applied": True}
            for item in selected
            if isinstance(item, dict)
        ]

    promotions = payload.get("partial_semantic_promotions")
    if isinstance(promotions, list) and promotions:
        current = resolved.get("selected") if isinstance(resolved.get("selected"), list) else []
        by_key = {_semantic_key(item): item for item in current if isinstance(item, dict)}
        for item in promotions:
            if not isinstance(item, dict):
                continue
            promoted = {
                **item,
                "partial_semantic_frame": bool(item.get("partial_semantic_frame", True)),
                "selection_status": "applied_correction",
                "correction_applied": True,
            }
            by_key[_semantic_key(promoted)] = promoted
        resolved["selected"] = [value for key, value in by_key.items() if key]
    if isinstance(resolved, dict):
        resolved["source"] = payload.get("source") or "manual_correction_overlay"
        resolved["corrected"] = True


def _semantic_key(record: dict[str, Any]) -> str:
    key_moment = str(record.get("key_moment") or "")
    if key_moment.startswith("T"):
        return "T"
    if key_moment.startswith("A"):
        return "A"
    if key_moment.startswith("L"):
        return "L"
    phase = str(record.get("phase_code") or "").strip().upper()
    if phase in KEYFRAME_KEYS:
        return phase
    if phase == "TAKEOFF":
        return "T"
    if phase in {"AIR", "APEX"}:
        return "A"
    if phase == "LANDING":
        return "L"
    return phase or str(record.get("frame_id") or "")


def _merge_report_note_correction(effective: dict[str, Any], payload: dict[str, Any]) -> None:
    report = effective["report"]
    note = _clean_text(payload.get("note"))
    if note:
        report["user_note_response"] = note
        report["corrected_note"] = True


def _merge_report_regeneration_correction(effective: dict[str, Any], payload: dict[str, Any]) -> None:
    report = payload.get("report")
    if isinstance(report, dict):
        effective["report"] = {**report, "corrected": True, "regenerated_from_corrections": True}
    if "force_score" in payload:
        effective["analysis"]["force_score"] = payload.get("force_score")


def _merge_target_lock_correction(effective: dict[str, Any], payload: dict[str, Any]) -> None:
    analysis = effective["analysis"]
    current = _deepcopy_dict(analysis.get("target_lock"))
    analysis["target_lock"] = {**current, **payload, "corrected": True}
    if "status" in payload:
        analysis["target_lock_status"] = payload["status"]


def build_effective_analysis_payload(
    analysis: Analysis,
    corrections: list[AnalysisCorrection] | None = None,
) -> dict[str, Any]:
    report = _deepcopy_dict(analysis.report)
    bio_data = _deepcopy_dict(analysis.bio_data)
    frame_motion_scores = _deepcopy_dict(analysis.frame_motion_scores)
    payload = {
        "analysis": {
            "id": analysis.id,
            "action_type": analysis.action_type,
            "action_subtype": analysis.action_subtype,
            "analysis_profile": analysis.analysis_profile,
            "skill_category": analysis.skill_category,
            "force_score": analysis.force_score,
            "target_lock": _deepcopy_dict(analysis.target_lock),
            "target_lock_status": analysis.target_lock_status,
            "corrections_applied": [],
        },
        "report": report,
        "bio_data": bio_data,
        "frame_motion_scores": frame_motion_scores,
        "corrections": [],
        "has_applied_corrections": False,
    }
    for correction in corrections or []:
        item = {
            "id": correction.id,
            "kind": correction.kind,
            "source": correction.source,
            "status": correction.status,
            "rationale": correction.rationale,
            "payload": correction.payload,
            "created_at": correction.created_at.isoformat() if correction.created_at else None,
            "applied_at": correction.applied_at.isoformat() if correction.applied_at else None,
        }
        payload["corrections"].append(item)
        if correction.status != "applied":
            continue
        if correction.kind == "action_label":
            _merge_action_correction(payload, correction.payload if isinstance(correction.payload, dict) else {})
        elif correction.kind == "keyframes":
            _merge_keyframe_correction(payload, correction.payload if isinstance(correction.payload, dict) else {})
        elif correction.kind == "report_note":
            _merge_report_note_correction(payload, correction.payload if isinstance(correction.payload, dict) else {})
        elif correction.kind == "report_regeneration":
            _merge_report_regeneration_correction(payload, correction.payload if isinstance(correction.payload, dict) else {})
        elif correction.kind == "target_lock":
            _merge_target_lock_correction(payload, correction.payload if isinstance(correction.payload, dict) else {})
        payload["analysis"]["corrections_applied"].append(item)
        payload["has_applied_corrections"] = True
    return payload


def apply_effective_payload_to_analysis(analysis: Any, effective: dict[str, Any]) -> Any:
    analysis_info = effective.get("analysis") if isinstance(effective.get("analysis"), dict) else {}
    analysis.action_type = str(analysis_info.get("action_type") or analysis.action_type)
    action_subtype = analysis_info.get("action_subtype")
    analysis.action_subtype = str(action_subtype) if action_subtype is not None else None
    analysis_profile = analysis_info.get("analysis_profile")
    analysis.analysis_profile = str(analysis_profile) if analysis_profile is not None else None
    if "target_lock" in analysis_info:
        analysis.target_lock = analysis_info.get("target_lock") if isinstance(analysis_info.get("target_lock"), dict) else analysis.target_lock
    if "target_lock_status" in analysis_info:
        status = analysis_info.get("target_lock_status")
        analysis.target_lock_status = str(status) if status is not None else None
    if "force_score" in analysis_info:
        analysis.force_score = analysis_info.get("force_score")
    if isinstance(effective.get("report"), dict):
        analysis.report = effective["report"]
    if isinstance(effective.get("bio_data"), dict):
        analysis.bio_data = effective["bio_data"]
    if isinstance(effective.get("frame_motion_scores"), dict):
        analysis.frame_motion_scores = effective["frame_motion_scores"]
    return analysis


async def list_analysis_corrections(session: AsyncSession, analysis_id: str) -> list[AnalysisCorrection]:
    result = await session.execute(
        select(AnalysisCorrection)
        .where(AnalysisCorrection.analysis_id == analysis_id)
        .order_by(AnalysisCorrection.created_at.asc(), AnalysisCorrection.id.asc())
    )
    return list(result.scalars().all())


async def create_analysis_correction(
    session: AsyncSession,
    analysis: Analysis,
    *,
    kind: str,
    payload: dict[str, Any],
    rationale: str | None = None,
    source: str | None = None,
    status: str | None = None,
) -> AnalysisCorrection:
    normalized_kind = normalize_correction_kind(kind)
    normalized_payload = normalize_correction_payload(normalized_kind, payload)
    normalized_source = normalize_correction_source(source)
    normalized_status = normalize_correction_status(status)
    correction = AnalysisCorrection(
        id=str(uuid4()),
        analysis_id=analysis.id,
        kind=normalized_kind,
        payload=normalized_payload,
        rationale=_limit_text(rationale),
        source=normalized_source,
        status=normalized_status,
        original_snapshot=_snapshot_for_kind(analysis, normalized_kind),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        applied_at=datetime.now(timezone.utc) if normalized_status == "applied" else None,
    )
    session.add(correction)
    await session.commit()
    await session.refresh(correction)
    return correction


async def apply_analysis_correction(
    session: AsyncSession,
    analysis: Analysis,
    correction_id: str,
) -> AnalysisCorrection:
    correction = await session.get(AnalysisCorrection, correction_id)
    if correction is None or correction.analysis_id != analysis.id:
        raise AnalysisCorrectionError("Correction not found.")
    if correction.status == "dismissed":
        raise AnalysisCorrectionError("Dismissed correction cannot be applied.")
    correction.status = "applied"
    correction.updated_at = datetime.now(timezone.utc)
    correction.applied_at = correction.applied_at or datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(correction)
    return correction


async def dismiss_analysis_correction(
    session: AsyncSession,
    analysis: Analysis,
    correction_id: str,
) -> AnalysisCorrection:
    correction = await session.get(AnalysisCorrection, correction_id)
    if correction is None or correction.analysis_id != analysis.id:
        raise AnalysisCorrectionError("Correction not found.")
    correction.status = "dismissed"
    correction.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(correction)
    return correction


async def effective_payload_for_analysis(session: AsyncSession, analysis: Analysis) -> dict[str, Any]:
    corrections = await list_analysis_corrections(session, analysis.id)
    return build_effective_analysis_payload(analysis, corrections)


async def effective_analysis_for_read(session: AsyncSession, analysis: Analysis) -> Any:
    effective = await effective_payload_for_analysis(session, analysis)
    clone = SimpleNamespace(**{column.name: getattr(analysis, column.name) for column in Analysis.__table__.columns})
    return apply_effective_payload_to_analysis(clone, effective)


def build_chat_share_text(
    analysis: Analysis,
    messages: list[Any],
    corrections: list[AnalysisCorrection],
    *,
    skater_name: str | None = None,
    include_pending_corrections: bool = True,
) -> str:
    title = f"{skater_name + ' · ' if skater_name else ''}{analysis.action_subtype or analysis.action_type}"
    report = analysis.report if isinstance(analysis.report, dict) else {}
    summary = str(report.get("summary") or "").strip()
    selected_messages = [message for message in messages if getattr(message, "role", "") in {"user", "assistant"}]
    applied = [item for item in corrections if item.status == "applied"]
    pending = [item for item in corrections if item.status == "proposed"]

    lines = [f"[IceBuddy AI追问] {title}"]
    if analysis.created_at:
        lines.append(f"分析时间：{analysis.created_at.date().isoformat()}")
    if summary:
        lines.extend(["", f"报告摘要：{summary}"])
    if selected_messages:
        lines.append("")
        lines.append("关键问答：")
        for message in selected_messages[-6:]:
            prefix = "问" if getattr(message, "role", "") == "user" else "答"
            content = re.sub(r"\s+", " ", str(getattr(message, "content", "") or "")).strip()
            if content:
                lines.append(f"{prefix}: {content}")
    if applied:
        lines.append("")
        lines.append("已应用修正：")
        for item in applied:
            lines.append(f"- {item.kind}: {_correction_share_summary(item)}")
    if include_pending_corrections and pending:
        lines.append("")
        lines.append("待确认修正：")
        for item in pending:
            lines.append(f"- {item.kind}: {_correction_share_summary(item)}")
    lines.extend(["", f"报告链接：/report/{analysis.id}", "由 IceBuddy 生成，仅供复盘参考"])
    return "\n".join(lines)


def _correction_share_summary(correction: AnalysisCorrection) -> str:
    payload = correction.payload if isinstance(correction.payload, dict) else {}
    if correction.kind == "action_label":
        label = payload.get("action_subtype") or payload.get("action_type")
        confirmation = payload.get("action_confirmation") if isinstance(payload.get("action_confirmation"), dict) else {}
        return str(label or confirmation.get("confirmed_action") or confirmation.get("jump_type") or correction.rationale or "动作识别修正")
    if correction.kind == "keyframes":
        key_frames = payload.get("key_frames") if isinstance(payload.get("key_frames"), dict) else {}
        return ", ".join(f"{key}={_frame_to_bio_value(value)}" for key, value in key_frames.items()) or str(correction.rationale or "关键帧修正")
    if correction.kind == "report_note":
        return str(payload.get("note") or correction.rationale or "报告备注修正")
    if correction.kind == "report_regeneration":
        return "已按人工修正重新生成报告"
    return str(correction.rationale or "修正")


def build_chat_share_image_payload(
    analysis: Analysis,
    messages: list[Any],
    corrections: list[AnalysisCorrection],
    *,
    skater_name: str | None = None,
) -> dict[str, Any]:
    report = analysis.report if isinstance(analysis.report, dict) else {}
    latest_question = next((message for message in reversed(messages) if getattr(message, "role", "") == "user"), None)
    latest_answer = next((message for message in reversed(messages) if getattr(message, "role", "") == "assistant"), None)
    return {
        "analysis_id": analysis.id,
        "title": f"{skater_name + ' · ' if skater_name else ''}{analysis.action_subtype or analysis.action_type}",
        "score": analysis.force_score,
        "summary": str(report.get("summary") or ""),
        "question": str(getattr(latest_question, "content", "") or ""),
        "answer": str(getattr(latest_answer, "content", "") or ""),
        "applied_corrections": [_correction_share_summary(item) for item in corrections if item.status == "applied"][:4],
        "pending_corrections": [_correction_share_summary(item) for item in corrections if item.status == "proposed"][:4],
        "report_url": f"/report/{analysis.id}",
    }
