from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.services.providers import get_active_provider, request_text_completion
from app.services.report import clean_json_text
from app.services.snowball import build_memory_context


logger = logging.getLogger(__name__)
PLAN_JSON_MAX_ATTEMPTS = 2


def _training_plan_timeout_seconds() -> float:
    raw_value = os.getenv("TRAINING_PLAN_AI_TIMEOUT_SECONDS", "120").strip()
    try:
        return max(45.0, float(raw_value))
    except ValueError:
        logger.warning("Invalid TRAINING_PLAN_AI_TIMEOUT_SECONDS=%r; using 120 seconds.", raw_value)
        return 120.0


def _training_plan_response_format() -> dict[str, str]:
    return {"type": "json_object"}


def _invalid_json_detail(exc: json.JSONDecodeError, raw_text: str) -> str:
    excerpt = raw_text[:300].replace("\n", "\\n")
    if excerpt:
        return f"{exc}; raw excerpt: {excerpt}"
    return f"{exc}; AI returned empty content"


async def _repair_training_plan_json(
    provider: Any,
    *,
    system_prompt: str,
    raw_content: str,
    error: json.JSONDecodeError,
    expected_shape: str = "object",
) -> Any:
    shape_instruction = (
        "ä¸€ä¸ªå®Œæ•´åˆæ³• JSON arrayï¼Œç¬¬ä¸€ä¸ªå­—ç¬¦å¿…é¡»æ˜¯ [ï¼Œæœ€åŽä¸€ä¸ªå­—ç¬¦å¿…é¡»æ˜¯ ]"
        if expected_shape == "array"
        else "ä¸€ä¸ªå®Œæ•´åˆæ³• JSON objectï¼Œç¬¬ä¸€ä¸ªå­—ç¬¦å¿…é¡»æ˜¯ {ï¼Œæœ€åŽä¸€ä¸ªå­—ç¬¦å¿…é¡»æ˜¯ }"
    )
    repair_prompt = (
        "ä¸Šä¸€æ¬¡è®­ç»ƒè®¡åˆ’è¾“å‡ºä¸æ˜¯åˆæ³• JSONã€‚"
        f"JSON è§£æžé”™è¯¯ï¼š{error}\n\n"
        f"è¯·ä¿®å¤ä¸‹é¢çš„å†…å®¹ï¼Œåªè¿”å›ž{shape_instruction}ï¼Œä¸è¦ Markdownã€è§£é‡Šæˆ–ä»£ç å—ã€‚\n\n"
        "å¿…é¡»ä¿æŒè¿™ä¸ªç»“æž„ï¼š"
        '{"title":"...","focus_skill":"...","days":[{"day":1,"theme":"...","sessions":[{"id":"d1s1","title":"...","duration":"6åˆ†é’Ÿ","description":"...","related_issue":"...","parent_tip":"...","is_office_trainable":true,"completed":false}]}]}\n\n'
        f"éœ€è¦ä¿®å¤çš„å†…å®¹ï¼š\n{raw_content[:6000]}"
    )
    repaired_content = await request_text_completion(
        provider,
        temperature=0.1,
        max_tokens=3200,
        timeout=_training_plan_timeout_seconds(),
        response_format=_training_plan_response_format(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": repair_prompt},
        ],
    )
    repaired_cleaned = _clean_plan_json_text(repaired_content)
    try:
        repaired = json.loads(repaired_cleaned)
    except json.JSONDecodeError as repair_error:
        logger.warning("Training plan JSON repair failed: %s | raw: %s", repair_error, repaired_cleaned[:500])
        raise PlanGenerationError(
            f"AI è¿”å›žçš„è®­ç»ƒè®¡åˆ’ä¸æ˜¯åˆæ³• JSONï¼š{_invalid_json_detail(repair_error, repaired_content)}"
        ) from repair_error
    if expected_shape == "array":
        if not isinstance(repaired, list):
            raise PlanGenerationError("AI è¿”å›žçš„è®­ç»ƒè®¡åˆ’ JSON ä¸æ˜¯æ•°ç»„ã€‚")
        return repaired
    if not isinstance(repaired, dict):
        raise PlanGenerationError("AI è¿”å›žçš„è®­ç»ƒè®¡åˆ’ JSON ä¸æ˜¯å¯¹è±¡ã€‚")
    return repaired


class PlanGenerationError(RuntimeError):
    """Raised when the training plan cannot be produced from an AI response."""


PLAN_DAY_THEMES = [
    (1, "核心稳定 + 轴心"),
    (2, "起跳发力"),
    (3, "落冰平衡"),
    (4, "柔韧恢复"),
    (5, "旋转速度"),
    (6, "综合模拟"),
    (7, "冰面验证"),
]

PLAN_SYSTEM_PROMPT = (
    "你是儿童花样滑冰启蒙教练，擅长给3-6岁小朋友设计安全、有趣、家长可陪练的训练。"
    "请根据分析报告、动作类型、孩子档案和历史记忆生成7天个性化训练计划。只输出合法 JSON，不含 markdown 或额外说明。"
    "所有项目必须低冲击、短时长、游戏化，不安排成人体能、负重、Bosu、旋转椅、长时间平板支撑或痛苦拉伸。"
    "不要套用固定模板；每一天都要能看出它为什么适合这次报告里的具体问题。"
    "每个训练项目必须写清 related_issue 和 parent_tip，方便家长知道它对应哪条诊断、该观察什么。"
)


def _clean_plan_json_text(raw_text: str) -> str:
    cleaned = clean_json_text(raw_text)
    stripped = raw_text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped

    fence_match = stripped
    if fence_match.startswith("```"):
        fence_match = fence_match.removeprefix("```json").removeprefix("```").strip()
        fence_match = fence_match.removesuffix("```").strip()
        if fence_match.startswith("[") and fence_match.endswith("]"):
            return fence_match

    array_start = stripped.find("[")
    array_end = stripped.rfind("]")
    object_start = stripped.find("{")
    if array_start != -1 and array_end > array_start and (object_start == -1 or array_start < object_start):
        return stripped[array_start : array_end + 1]
    return cleaned

EXTEND_PLAN_SYSTEM_PROMPT = (
    "你是儿童花样滑冰启蒙教练，擅长给3-6岁小朋友设计安全、有趣、家长可陪练的训练。"
    "请根据分析报告、已完成训练和孩子档案续写7天个性化训练计划。"
    "只输出 JSON，不含任何 markdown 包裹或额外说明。"
    "所有新增项目必须低冲击、短时长、游戏化，并继续回应原报告里的主要问题。"
    "每个新增训练项目必须写清 related_issue 和 parent_tip。"
)


def _fallback_sessions(day_number: int, action_type: str) -> list[dict[str, Any]]:
    fallback_by_day = {
        1: [
            ("小企鹅站直线", "6分钟", "在垫子上站成小企鹅，头顶想象有皇冠，家长数到10。", True, "身体控制", "看头和肚脐是否一直朝前。"),
            ("单脚小树游戏", "6分钟", "扶墙单脚站，另一只脚轻点地，左右各做5次。", True, "单脚平衡", "只要站稳即可，不追求抬腿高度。"),
        ],
        2: [
            ("火箭膝盖弹簧", "6分钟", "双脚站稳，轻轻弯膝再站高，像小火箭起飞。", True, "准备发力", "膝盖弯伸要轻，不要猛蹲猛跳。"),
            ("小兔轻跳线", "6分钟", "在地上贴一条线，双脚小跳越线，落地要安静。", True, "轻跳节奏", "听落地声音是否越来越轻。"),
        ],
        3: [
            ("小飞机落地", "7分钟", "小跳后单脚轻落，双臂打开像飞机，停住3秒。", True, "落冰稳定", "落地后能停住3秒就算成功。"),
            ("软膝盖刹车", "6分钟", "走三步后弯膝停住，练习落冰时的缓冲。", True, "落冰缓冲", "提醒膝盖像小弹簧，不要锁死。"),
        ],
        4: [
            ("彩虹摆腿", "6分钟", "扶墙前后小摆腿，幅度舒服即可，不追求高度。", True, "活动范围", "动作要慢，孩子说疼就立刻停。"),
            ("小猫伸懒腰", "6分钟", "做猫背、伸手、脚踝绕圈，放松不疼痛。", True, "恢复放松", "观察呼吸是否放松，不做硬拉伸。"),
        ],
        5: [
            ("抱小熊收手", "6分钟", "双臂打开后抱住小熊玩偶，练习快速但轻松地收手。", True, "手臂配合", "肩膀保持轻松，别耸肩。"),
            ("原地半圈找爸爸妈妈", "6分钟", "原地小半圈转身，转完看向家长，保持站稳。", True, "方向感", "转完能马上找到家长方向。"),
        ],
        6: [
            ("三段小剧场", "8分钟", f"把{action_type}分成准备、起跳、落地三幕，像表演一样连起来。", True, "动作串联", "每一幕都能说出一个小目标。"),
            ("音乐节奏走跳", "8分钟", "放一首喜欢的音乐，按节奏做准备、轻跳、稳稳停。", True, "节奏保持", "动作跟音乐走，不追求速度。"),
        ],
        7: [
            ("冰上小目标验证", "12分钟", "在教练或家长陪同下，上冰完成3次最稳动作。", False, "冰上迁移", "只比稳定度，不比难度。"),
            ("最佳一次贴星星", "8分钟", "选出今天最稳的一次，记录一个小星星奖励。", False, "正向反馈", "让孩子说出这次哪里最稳。"),
        ],
    }

    return [
        {
            "id": f"d{day_number}s{index}",
            "title": title,
            "duration": duration,
            "description": description,
            "is_office_trainable": False if day_number == 7 else is_office_trainable,
            "completed": False,
            "related_issue": related_issue,
            "parent_tip": parent_tip,
        }
        for index, (title, duration, description, is_office_trainable, related_issue, parent_tip) in enumerate(
            fallback_by_day[day_number],
            start=1,
        )
    ]


def _first_report_issue(report: dict[str, Any]) -> tuple[str, str]:
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    for raw_issue in issues:
        if not isinstance(raw_issue, dict):
            continue
        category = str(raw_issue.get("category") or "训练重点").strip()
        description = str(raw_issue.get("description") or "").strip()
        if category or description:
            return category or "训练重点", description
    focus = str(report.get("training_focus") or "").strip()
    return "训练重点", focus


def _compact_issue_label(category: str, description: str, fallback: str) -> str:
    text = f"{category}：{description}" if description else category
    text = text.strip("： ")
    if not text:
        text = fallback
    return text[:16]


def _personalized_fallback_theme(day_number: int, default_theme: str, focus_skill: str, issue_category: str) -> str:
    if day_number == 1:
        return f"{issue_category[:8] or focus_skill[:8]}小侦探"
    if day_number == 2:
        return f"{focus_skill[:8]}节奏日"
    if day_number == 3:
        return f"{issue_category[:8] or '稳定'}停一停"
    if day_number == 4:
        return f"{focus_skill[:8]}轻松恢复"
    if day_number == 5:
        return f"{focus_skill[:8]}方向游戏"
    if day_number == 6:
        return f"{focus_skill[:8]}三幕串联"
    if day_number == 7:
        return f"{focus_skill[:8]}冰上验证"
    return default_theme


def build_fallback_plan(
    action_type: str,
    report: dict[str, Any],
    skater_context: str | None = None,
) -> dict[str, Any]:
    focus_hint = str(report.get("training_focus") or action_type).strip()
    focus_skill = focus_hint[:28] if focus_hint else f"{action_type}基础"
    issue_category, issue_description = _first_report_issue(report)
    issue_label = _compact_issue_label(issue_category, issue_description, focus_skill)
    title = "7天亲子滑冰小练习"
    if skater_context and any(name in skater_context for name in ("弟弟", "昭昭", "didi", "zhaozao")):
        title = "7天亲子冰感小游戏"

    days: list[dict[str, Any]] = []
    for day_number, default_theme in PLAN_DAY_THEMES:
        sessions = _fallback_sessions(day_number, action_type)
        for session in sessions:
            session["related_issue"] = issue_label if day_number in {1, 2, 3, 6, 7} else (session.get("related_issue") or issue_label)
            if day_number == 1:
                session["parent_tip"] = "只看是否更稳更放松。"
            elif day_number == 2:
                session["parent_tip"] = "动作轻一点，节奏不断。"
            elif day_number == 3:
                session["parent_tip"] = "停住3秒就是成功。"
            elif day_number == 7:
                session["parent_tip"] = "上冰只验证稳定一次。"
        days.append(
            {
                "day": day_number,
                "theme": _personalized_fallback_theme(day_number, default_theme, focus_skill, issue_category),
                "sessions": sessions,
            }
        )

    return {
        "title": title,
        "focus_skill": focus_skill,
        "days": days,
        "generation_source": "fallback",
        "generation_note": "AI 训练计划暂不可用，已按报告问题生成安全兜底计划。",
    }


def normalize_plan(
    payload: dict[str, Any],
    action_type: str,
    report: dict[str, Any] | None = None,
    skater_context: str | None = None,
) -> dict[str, Any]:
    fallback = build_fallback_plan(action_type, report or {}, skater_context)
    fallback_days = {day["day"]: day for day in fallback["days"]}
    days_by_index = {int(day.get("day", 0)): day for day in payload.get("days", []) if isinstance(day, dict)}
    normalized_days: list[dict[str, Any]] = []

    for day_number, fallback_theme in PLAN_DAY_THEMES:
        raw_day = days_by_index.get(day_number, {})
        theme = str(raw_day.get("theme") or fallback_theme).strip() or fallback_theme
        raw_sessions = raw_day.get("sessions", [])
        if not isinstance(raw_sessions, list) or not raw_sessions:
            raw_sessions = fallback_days[day_number]["sessions"]

        sessions: list[dict[str, Any]] = []
        for index, session in enumerate(raw_sessions[:2], start=1):
            if not isinstance(session, dict):
                continue
            fallback_session = fallback_days[day_number]["sessions"][min(index - 1, len(fallback_days[day_number]["sessions"]) - 1)]
            description = str(session.get("description", "")).strip()
            related_issue = str(session.get("related_issue") or session.get("why") or fallback_session.get("related_issue") or "").strip()
            parent_tip = str(session.get("parent_tip") or session.get("coach_tip") or fallback_session.get("parent_tip") or "").strip()
            sessions.append(
                {
                    "id": str(session.get("id") or f"d{day_number}s{index}"),
                    "title": str(session.get("title", f"{theme}小游戏 {index}")).strip(),
                    "duration": str(session.get("duration", "6分钟")).strip(),
                    "description": description or str(fallback_session.get("description", "")).strip(),
                    "is_office_trainable": False if day_number == 7 else bool(session.get("is_office_trainable", True)),
                    "completed": bool(session.get("completed", False)),
                    "related_issue": related_issue or None,
                    "parent_tip": parent_tip or None,
                }
            )

        if not sessions:
            sessions = fallback_days[day_number]["sessions"]

        normalized_days.append(
            {
                "day": day_number,
                "theme": theme,
                "sessions": sessions,
            }
        )

    return {
        "title": str(payload.get("title", fallback["title"])).strip() or fallback["title"],
        "focus_skill": str(payload.get("focus_skill", fallback["focus_skill"])).strip() or fallback["focus_skill"],
        "days": normalized_days,
        "generation_source": str(payload.get("generation_source") or "ai").strip() or "ai",
        "generation_note": str(payload.get("generation_note") or "").strip() or None,
    }


def _require_complete_plan_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PlanGenerationError("AI 未返回训练计划 JSON 对象。")

    days = payload.get("days")
    if not isinstance(days, list):
        raise PlanGenerationError("AI 返回的训练计划缺少 days 数组。")

    expected_days = {day for day, _ in PLAN_DAY_THEMES}
    received_days: set[int] = set()
    for raw_day in days:
        if not isinstance(raw_day, dict):
            continue
        try:
            day_number = int(raw_day.get("day", 0) or 0)
        except (TypeError, ValueError):
            continue
        sessions = raw_day.get("sessions")
        if day_number in expected_days and isinstance(sessions, list) and sessions:
            received_days.add(day_number)

    missing_days = sorted(expected_days - received_days)
    if missing_days:
        raise PlanGenerationError(f"AI 返回的训练计划不完整，缺少第 {missing_days} 天。")

    return payload


def _require_regenerated_days_payload(payload: Any, required_days: list[int]) -> list[dict[str, Any]]:
    raw_days = payload if isinstance(payload, list) else payload.get("days", []) if isinstance(payload, dict) else []
    if not isinstance(raw_days, list):
        raise PlanGenerationError("AI 未返回续期训练计划数组。")

    expected_days = set(required_days)
    valid_days: list[dict[str, Any]] = []
    received_days: set[int] = set()
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            continue
        try:
            day_number = int(raw_day.get("day", 0) or 0)
        except (TypeError, ValueError):
            continue
        sessions = raw_day.get("sessions")
        if day_number in expected_days and isinstance(sessions, list) and sessions:
            valid_days.append(raw_day)
            received_days.add(day_number)

    missing_days = sorted(expected_days - received_days)
    if missing_days:
        raise PlanGenerationError(f"AI 返回的续期计划不完整，缺少第 {missing_days} 天。")

    return valid_days


def summarize_completed_sessions(plan_json: dict[str, Any], completed_days: list[int]) -> str:
    days = plan_json.get("days", []) if isinstance(plan_json, dict) else []
    lines: list[str] = []
    for raw_day in days:
        if not isinstance(raw_day, dict):
            continue
        day_number = int(raw_day.get("day", 0) or 0)
        if day_number not in completed_days:
            continue
        theme = str(raw_day.get("theme", "")).strip()
        sessions = raw_day.get("sessions", [])
        completed_sessions = [
            session
            for session in sessions
            if isinstance(session, dict) and bool(session.get("completed"))
        ]
        if completed_sessions:
            session_summary = "；".join(
                f"{str(session.get('title', '')).strip()}：{str(session.get('description', '')).strip()}"
                for session in completed_sessions
            )
        else:
            session_summary = "已标记完成当天训练。"
        lines.append(f"Day {day_number}（{theme}）：{session_summary}")
    return "\n".join(lines)


def merge_extended_plan(
    original_plan: dict[str, Any],
    regenerated_days: list[dict[str, Any]],
    completed_days: list[int],
) -> dict[str, Any]:
    original_days = original_plan.get("days", []) if isinstance(original_plan, dict) else []
    completed_day_set = set(completed_days)
    regenerated_map = {
        int(day.get("day", 0)): day
        for day in regenerated_days
        if isinstance(day, dict) and int(day.get("day", 0) or 0)
    }
    merged_days: list[dict[str, Any]] = []

    for raw_day in original_days:
        if not isinstance(raw_day, dict):
            continue
        day_number = int(raw_day.get("day", 0) or 0)
        if day_number in completed_day_set or day_number not in regenerated_map:
            merged_days.append(raw_day)
            continue
        regenerated_day = regenerated_map[day_number]
        merged_days.append(
            {
                "day": day_number,
                "theme": str(regenerated_day.get("theme", raw_day.get("theme", ""))).strip() or str(raw_day.get("theme", "")),
                "sessions": regenerated_day.get("sessions", []),
            }
        )

    return {
        "title": str(original_plan.get("title", "")).strip(),
        "focus_skill": str(original_plan.get("focus_skill", "")).strip(),
        "days": merged_days,
    }


async def generate_training_plan(
    action_type: str,
    report: dict[str, Any],
    skater_context: str | None = None,
    skater_id: str | None = None,
    variation_key: str | None = None,
) -> dict[str, Any]:
    try:
        provider = await get_active_provider("report")
        memory_context = await build_memory_context(skater_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Training plan provider setup failed: %s", exc)
        raise PlanGenerationError(f"训练计划 AI 供应商不可用：{exc}") from exc
    system_prompt = PLAN_SYSTEM_PROMPT if not memory_context else f"{PLAN_SYSTEM_PROMPT}\n\n{memory_context}"

    issues_text = "\n".join(
        f"- {issue.get('category', '未分类')}：{issue.get('description', '')}（{issue.get('severity', 'low')}）"
        for issue in report.get("issues", [])
    ) or "- 当前暂无明确问题，请围绕基础动作稳定性安排训练。"
    user_note = (
        str(report.get("user_note") or report.get("note") or report.get("analysis_note") or "")
        .strip()
    )
    day_guidance = "\n".join(
        [
            "Day 1: 从本次最明显的问题出发，建立低冲击身体控制。",
            "Day 2: 练动作准备和发力节奏，但必须和本次动作类型相关。",
            "Day 3: 练最需要修正的平衡、落冰或收势细节。",
            "Day 4: 用轻柔活动恢复，并服务于前3天发现的问题。",
            "Day 5: 练动作中的转体、方向感或手臂配合；如果动作不是旋转，也不要硬写旋转速度。",
            "Day 6: 把报告里的重点串成短小组合模拟。",
            "Day 7: 只安排冰上验证，所有项目 is_office_trainable=false。",
        ]
    )

    try:
        raw_content = await request_text_completion(
            provider,
            temperature=0.55,
            max_tokens=3200,
            timeout=_training_plan_timeout_seconds(),
            response_format=_training_plan_response_format(),
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                    f"练习对象：{skater_context or '儿童滑冰学员'}\n"
                    f"动作类型：{action_type}\n"
                    f"总体评价：{report.get('summary', '')}\n"
                    f"主要问题：{issues_text}\n"
                    f"训练重点：{report.get('training_focus', '')}\n"
                    f"家长/教练备注：{user_note or '无'}\n"
                    f"变化种子：{variation_key or 'initial'}\n\n"
                    "请生成适合小朋友的7天训练计划。每天的 theme 必须由 AI 根据本次报告重新命名，"
                    "不要直接照抄“核心稳定/起跳发力/落冰平衡/柔韧恢复/旋转速度”等固定模板。"
                    "每天至少1个训练项目要明确回应上面的主要问题或训练重点，优先处理最高 severity 的问题。\n"
                    "如果报告或备注显示孩子害怕、年龄小、动作不稳定，必须降低冲击、缩短时长，并用亲子游戏包装。\n\n"
                    "7天进阶逻辑参考如下，但 theme 和训练项目必须个性化：\n"
                    f"{day_guidance}\n\n"
                    "儿童安全规则：\n"
                    "1. 每天2项，每项5-10分钟，最多12分钟。\n"
                    "2. 用游戏语言描述，例如小企鹅、小飞机、小火箭。\n"
                    "3. 家中练习必须低冲击，可在瑜伽垫上完成，需要家长陪同。\n"
                    "4. 不要安排平板支撑超过20秒、深蹲力量训练、阻力带、Bosu、旋转椅、负重、痛苦拉伸。\n"
                    "5. Day 7 所有项目必须 is_office_trainable=false。\n"
                    "6. 每个 description 控制在45个中文字以内，并写成孩子听得懂的动作玩法。\n"
                    "7. 每个 session 必须有 related_issue（对应报告问题或训练重点，8-16字）和 parent_tip（家长观察点，18字以内）。\n"
                    "8. 不要连续两天使用相同的 title、description、related_issue 或 parent_tip。\n"
                    "输出完整合法 JSON，结构如下：\n"
                    "{"
                    '"title":"7天亲子滑冰小练习",'
                    '"focus_skill":"根据报告生成的具体训练重点",'
                    '"days":[{"day":1,"theme":"贴合本次问题的当天主题","sessions":[{"id":"d1s1","title":"游戏化训练名","duration":"6分钟","description":"回应报告问题的儿童练习描述。","related_issue":"落冰缓冲不足","parent_tip":"听落地声音是否变轻","is_office_trainable":true,"completed":false}]}]'
                    "}"
                    ),
                },
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Training plan completion failed: %s", exc)
        raise PlanGenerationError(f"训练计划 AI 调用失败：{exc}") from exc
    cleaned = _clean_plan_json_text(raw_content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Training plan JSON parse failed: %s | raw: %s", exc, cleaned[:500])
        parsed = await _repair_training_plan_json(
            provider,
            system_prompt=system_prompt,
            raw_content=raw_content,
            error=exc,
        )

    return normalize_plan(_require_complete_plan_payload(parsed), action_type, report, skater_context)


async def extend_training_plan(
    *,
    original_plan: dict[str, Any],
    completed_days: list[int],
    action_type: str,
    report: dict[str, Any],
    skater_context: str | None = None,
    skater_id: str | None = None,
) -> dict[str, Any]:
    normalized_original = normalize_plan(original_plan, action_type, report, skater_context)
    valid_completed_days = sorted({day for day in completed_days if 1 <= day <= 7})
    remaining_days = [day for day, _ in PLAN_DAY_THEMES if day not in valid_completed_days]
    if not remaining_days:
        return normalized_original

    try:
        provider = await get_active_provider("report")
        memory_context = await build_memory_context(skater_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Extended training plan provider setup failed: %s", exc)
        raise PlanGenerationError(f"训练计划续期 AI 供应商不可用：{exc}") from exc
    system_prompt = EXTEND_PLAN_SYSTEM_PROMPT if not memory_context else f"{EXTEND_PLAN_SYSTEM_PROMPT}\n\n{memory_context}"

    completed_sessions_summary = summarize_completed_sessions(normalized_original, valid_completed_days) or "暂无已完成摘要。"
    remaining_theme_lines = "\n".join(
        f"Day {day}: {theme}"
        for day, theme in PLAN_DAY_THEMES
        if day in remaining_days
    )
    report_summary = str(report.get("summary", "")).strip() or str(report.get("training_focus", "")).strip() or action_type
    issues_text = "\n".join(
        f"- {issue.get('category', '未分类')}：{issue.get('description', '')}（{issue.get('severity', 'low')}）"
        for issue in report.get("issues", [])
        if isinstance(issue, dict)
    ) or "- 当前暂无明确问题，请围绕基础动作稳定性安排训练。"
    user_note = (
        str(report.get("user_note") or report.get("note") or report.get("analysis_note") or "")
        .strip()
    )

    try:
        raw_content = await request_text_completion(
            provider,
            temperature=0.45,
            max_tokens=2200,
            timeout=_training_plan_timeout_seconds(),
            response_format=_training_plan_response_format(),
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                    f"原训练计划已完成前 {valid_completed_days} 天。\n"
                    f"以下是已完成的训练摘要：\n{completed_sessions_summary}\n\n"
                    f"练习对象：{skater_context or '儿童滑冰学员'}\n"
                    f"动作类型：{action_type}\n"
                    f"原始报告摘要：{report_summary}\n"
                    f"主要问题：\n{issues_text}\n"
                    f"训练重点：{report.get('training_focus', '')}\n"
                    f"家长/教练备注：{user_note or '无'}\n\n"
                    f"请重新生成第 {remaining_days} 天的训练内容，\n"
                    "保持已完成天数不变；剩余天数的 theme 和 sessions 必须继续回应原报告问题与已完成进度，避免重复已完成项目。\n"
                    f"{remaining_theme_lines}\n"
                    "儿童安全规则：每天2项，每项5-10分钟，低冲击、游戏化、家长可监督；不要安排负重、Bosu、旋转椅、痛苦拉伸或成人体能。\n"
                    "每个 session 必须包含 related_issue 和 parent_tip，让后续计划能看出对应哪条诊断、家长该看什么。\n"
                    "Day 7 所有项目必须 is_office_trainable=false。\n"
                    "只输出需要更新的天数的 JSON 数组，格式与原计划相同。"
                    ),
                },
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Extended training plan completion failed: %s", exc)
        raise PlanGenerationError(f"训练计划续期 AI 调用失败：{exc}") from exc
    cleaned = _clean_plan_json_text(raw_content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Extended training plan JSON parse failed: %s | raw: %s", exc, cleaned[:500])
        parsed = await _repair_training_plan_json(
            provider,
            system_prompt=system_prompt,
            raw_content=raw_content,
            error=exc,
            expected_shape="array",
        )

    regenerated_days = _require_regenerated_days_payload(parsed, remaining_days)
    normalized_regenerated = normalize_plan(
        {
            "title": normalized_original["title"],
            "focus_skill": normalized_original["focus_skill"],
            "days": regenerated_days,
        },
        action_type,
        report,
        skater_context,
    )["days"]

    merged = merge_extended_plan(normalized_original, normalized_regenerated, valid_completed_days)
    return normalize_plan(merged, action_type, report, skater_context)
