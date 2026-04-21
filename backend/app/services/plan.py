from __future__ import annotations

import json
import logging
from typing import Any

from app.services.providers import get_active_provider, request_text_completion
from app.services.report import clean_json_text
from app.services.snowball import build_memory_context


logger = logging.getLogger(__name__)

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
    "请根据分析报告生成7天个性化训练计划。只输出合法 JSON，不含 markdown 或额外说明。"
    "所有项目必须低冲击、短时长、游戏化，不安排成人体能、负重、Bosu、旋转椅、长时间平板支撑或痛苦拉伸。"
)

EXTEND_PLAN_SYSTEM_PROMPT = (
    "你是专业花样滑冰教练，请根据分析报告生成7天个性化训练计划。"
    "只输出 JSON，不含任何 markdown 包裹或额外说明。"
)


def _fallback_sessions(day_number: int, action_type: str) -> list[dict[str, Any]]:
    fallback_by_day = {
        1: [
            ("小企鹅站直线", "6分钟", "在垫子上站成小企鹅，头顶想象有皇冠，家长数到10。", True),
            ("单脚小树游戏", "6分钟", "扶墙单脚站，另一只脚轻点地，左右各做5次。", True),
        ],
        2: [
            ("火箭膝盖弹簧", "6分钟", "双脚站稳，轻轻弯膝再站高，像小火箭起飞。", True),
            ("小兔轻跳线", "6分钟", "在地上贴一条线，双脚小跳越线，落地要安静。", True),
        ],
        3: [
            ("小飞机落地", "7分钟", "小跳后单脚轻落，双臂打开像飞机，停住3秒。", True),
            ("软膝盖刹车", "6分钟", "走三步后弯膝停住，练习落冰时的缓冲。", True),
        ],
        4: [
            ("彩虹摆腿", "6分钟", "扶墙前后小摆腿，幅度舒服即可，不追求高度。", True),
            ("小猫伸懒腰", "6分钟", "做猫背、伸手、脚踝绕圈，放松不疼痛。", True),
        ],
        5: [
            ("抱小熊收手", "6分钟", "双臂打开后抱住小熊玩偶，练习快速但轻松地收手。", True),
            ("原地半圈找爸爸妈妈", "6分钟", "原地小半圈转身，转完看向家长，保持站稳。", True),
        ],
        6: [
            ("三段小剧场", "8分钟", f"把{action_type}分成准备、起跳、落地三幕，像表演一样连起来。", True),
            ("音乐节奏走跳", "8分钟", "放一首喜欢的音乐，按节奏做准备、轻跳、稳稳停。", True),
        ],
        7: [
            ("冰上小目标验证", "12分钟", "在教练或家长陪同下，上冰完成3次最稳动作。", False),
            ("最佳一次贴星星", "8分钟", "选出今天最稳的一次，记录一个小星星奖励。", False),
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
        }
        for index, (title, duration, description, is_office_trainable) in enumerate(
            fallback_by_day[day_number],
            start=1,
        )
    ]


def build_fallback_plan(
    action_type: str,
    report: dict[str, Any],
    skater_context: str | None = None,
) -> dict[str, Any]:
    focus_hint = str(report.get("training_focus") or action_type).strip()
    focus_skill = focus_hint[:28] if focus_hint else f"{action_type}基础"
    title = "7天亲子滑冰小练习"
    if skater_context and any(name in skater_context for name in ("弟弟", "昭昭", "didi", "zhaozao")):
        title = "7天亲子冰感小游戏"

    return {
        "title": title,
        "focus_skill": focus_skill,
        "days": [
            {
                "day": day_number,
                "theme": theme,
                "sessions": _fallback_sessions(day_number, action_type),
            }
            for day_number, theme in PLAN_DAY_THEMES
        ],
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

    for day_number, theme in PLAN_DAY_THEMES:
        raw_day = days_by_index.get(day_number, {})
        raw_sessions = raw_day.get("sessions", [])
        if not isinstance(raw_sessions, list) or not raw_sessions:
            raw_sessions = fallback_days[day_number]["sessions"]

        sessions: list[dict[str, Any]] = []
        for index, session in enumerate(raw_sessions[:2], start=1):
            if not isinstance(session, dict):
                continue
            sessions.append(
                {
                    "id": str(session.get("id") or f"d{day_number}s{index}"),
                    "title": str(session.get("title", f"{theme}小游戏 {index}")).strip(),
                    "duration": str(session.get("duration", "6分钟")).strip(),
                    "description": str(session.get("description", "")).strip(),
                    "is_office_trainable": False if day_number == 7 else bool(session.get("is_office_trainable", True)),
                    "completed": bool(session.get("completed", False)),
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
    }


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
) -> dict[str, Any]:
    provider = await get_active_provider("report")
    memory_context = await build_memory_context(skater_id)
    system_prompt = PLAN_SYSTEM_PROMPT if not memory_context else f"{PLAN_SYSTEM_PROMPT}\n\n{memory_context}"

    issues_text = "\n".join(
        f"- {issue.get('category', '未分类')}：{issue.get('description', '')}（{issue.get('severity', 'low')}）"
        for issue in report.get("issues", [])
    ) or "- 当前暂无明确问题，请围绕基础动作稳定性安排训练。"

    raw_content = await request_text_completion(
        provider,
        temperature=0.25,
        max_tokens=3200,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"练习对象：{skater_context or '儿童滑冰学员'}\n"
                    f"动作类型：{action_type}\n"
                    f"总体评价：{report.get('summary', '')}\n"
                    f"主要问题：{issues_text}\n"
                    f"训练重点：{report.get('training_focus', '')}\n\n"
                    "请生成适合小朋友的7天训练计划，严格按以下主题顺序：\n"
                    "Day 1: 核心稳定 + 轴心\n"
                    "Day 2: 起跳发力\n"
                    "Day 3: 落冰平衡\n"
                    "Day 4: 柔韧恢复\n"
                    "Day 5: 旋转速度\n"
                    "Day 6: 综合模拟\n"
                    "Day 7: 冰面验证\n\n"
                    "儿童安全规则：\n"
                    "1. 每天2项，每项5-10分钟，最多12分钟。\n"
                    "2. 用游戏语言描述，例如小企鹅、小飞机、小火箭。\n"
                    "3. 家中练习必须低冲击，可在瑜伽垫上完成，需要家长陪同。\n"
                    "4. 不要安排平板支撑超过20秒、深蹲力量训练、阻力带、Bosu、旋转椅、负重、痛苦拉伸。\n"
                    "5. Day 7 所有项目必须 is_office_trainable=false。\n"
                    "6. 每个 description 控制在45个中文字以内。\n"
                    "输出完整合法 JSON，结构如下：\n"
                    "{"
                    '"title":"7天亲子滑冰小练习",'
                    '"focus_skill":"跳跃基础",'
                    '"days":[{"day":1,"theme":"核心稳定 + 轴心","sessions":[{"id":"d1s1","title":"小企鹅站直线","duration":"6分钟","description":"头顶皇冠站直，家长数到10。","is_office_trainable":true,"completed":false}]}]'
                    "}"
                ),
            },
        ],
    )
    cleaned = clean_json_text(raw_content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Training plan JSON parse failed, using child-safe fallback plan: %s", exc)
        return build_fallback_plan(action_type, report, skater_context)

    return normalize_plan(parsed, action_type, report, skater_context)


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

    provider = await get_active_provider("report")
    memory_context = await build_memory_context(skater_id)
    system_prompt = EXTEND_PLAN_SYSTEM_PROMPT if not memory_context else f"{EXTEND_PLAN_SYSTEM_PROMPT}\n\n{memory_context}"

    completed_sessions_summary = summarize_completed_sessions(normalized_original, valid_completed_days) or "暂无已完成摘要。"
    remaining_theme_lines = "\n".join(
        f"Day {day}: {theme}"
        for day, theme in PLAN_DAY_THEMES
        if day in remaining_days
    )
    report_summary = str(report.get("summary", "")).strip() or str(report.get("training_focus", "")).strip() or action_type

    raw_content = await request_text_completion(
        provider,
        temperature=0.25,
        max_tokens=2200,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"原训练计划已完成前 {valid_completed_days} 天。\n"
                    f"以下是已完成的训练摘要：\n{completed_sessions_summary}\n\n"
                    f"请重新生成第 {remaining_days} 天的训练内容，\n"
                    "保持原有7天主题顺序，\n"
                    f"{remaining_theme_lines}\n"
                    "只输出需要更新的天数的 JSON 数组，格式与原计划相同。\n"
                    f"参考原始报告背景：{report_summary}"
                ),
            },
        ],
    )
    cleaned = clean_json_text(raw_content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Extended training plan JSON parse failed, reusing original remaining days: %s", exc)
        parsed = [day for day in normalized_original["days"] if day["day"] in remaining_days]

    regenerated_days = parsed if isinstance(parsed, list) else parsed.get("days", [])
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
