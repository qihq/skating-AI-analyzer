from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Analysis, Skater, SkaterSkill, SkillNode


UNLOCKED_STATUSES = {"unlocked"}
LEVEL_THRESHOLDS = [
    (1, 0, "冰场小企鹅", "🐧"),
    (2, 200, "冰上小熊猫", "🐼"),
    (3, 600, "冰雪小狐狸", "🦊"),
    (4, 1500, "冰雪小骑士", "🏅"),
    (5, 3000, "冰雪小王子", "👑"),
    (6, 6000, "冰雪勇士", "⚔️"),
    (7, 10000, "冰上骑士长", "🛡️"),
    (8, 16000, "冰雪传说", "🌟"),
    (9, 25000, "冰上英雄", "🦅"),
    (10, 40000, "冰雪大师", "🏆"),
]
STAGE_DEFINITIONS = {
    1: {"name": "冰场启蒙", "description": "学会站稳、犁式刹车、基础前滑。"},
    2: {"name": "基础转体、步法和停止", "description": "前后方向转换、刃感、肩髋协调。"},
    3: {"name": "单跳 + 联合旋转", "description": "单周跳跃系列、蹲燕旋转组合。"},
    4: {"name": "双跳 + 竞技", "description": "Axel、双周跳、竞技节目。"},
}


def _node(
    skill_id: str,
    *,
    chapter: str,
    chapter_order: int,
    stage: int,
    group_name: str,
    sort_order: int,
    name: str,
    emoji: str,
    xp: int,
    requires: list[str] | None = None,
    unlock_config: dict[str, Any] | None = None,
    action_type: str | None = None,
    is_parent_only: bool = False,
    search_terms: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": skill_id,
        "chapter": chapter,
        "chapter_order": chapter_order,
        "stage": stage,
        "stage_name": STAGE_DEFINITIONS[stage]["name"],
        "group_name": group_name,
        "sort_order": sort_order,
        "name": name,
        "emoji": emoji,
        "xp": xp,
        "requires": requires or [],
        "unlock_config": unlock_config,
        "action_type": action_type,
        "is_parent_only": is_parent_only,
        "metadata_json": {"search_terms": search_terms or [name]},
    }


SKILL_CATALOG: list[dict[str, Any]] = [
    _node("ss_all", chapter="snowplow", chapter_order=0, stage=1, group_name="冰上启蒙", sort_order=1, name="犁式刹车全套", emoji="🐧", xp=120, search_terms=["犁式刹车", "snowplow", "刹车"]),
    _node("basic_all", chapter="basic", chapter_order=1, stage=1, group_name="基础前滑", sort_order=2, name="基础滑冰技能全套", emoji="⛸️", xp=180, search_terms=["基础滑冰", "basic", "基础前滑"]),
    _node("fs1_stroking", chapter="fs1", chapter_order=2, stage=2, group_name="后滑安全感", sort_order=1, name="前向有力蹬冰", emoji="⛸️", xp=60, requires=["basic_all"], action_type="步法", unlock_config={"score": {"threshold": 60, "consecutive": 2, "action_type": "步法"}}, search_terms=["前向有力蹬冰", "蹬冰"]),
    _node("fs1_fwd_edges", chapter="fs1", chapter_order=2, stage=2, group_name="弧线与刃感", sort_order=2, name="前外/前内连续刃", emoji="🛤️", xp=60, requires=["basic_all"], action_type="步法", unlock_config={"score": {"threshold": 60, "consecutive": 2, "action_type": "步法"}}, search_terms=["前外/前内连续刃", "连续刃", "前外刃", "前内刃"]),
    _node("fs1_bk_three_turn", chapter="fs1", chapter_order=2, stage=2, group_name="肩髋同步转体", sort_order=3, name="后外三转弯", emoji="🔄", xp=80, requires=["basic_all"], action_type="步法", unlock_config={"score": {"threshold": 60, "consecutive": 2, "action_type": "步法"}}, search_terms=["后外三转弯", "三转弯"]),
    _node("fs1_spin_scratch", chapter="fs1", chapter_order=2, stage=2, group_name="旋转启蒙", sort_order=4, name="直立旋转3圈", emoji="💃", xp=100, requires=["basic_all"], action_type="旋转", unlock_config={"score": {"threshold": 65, "consecutive": 3, "action_type": "旋转"}}, search_terms=["直立旋转", "scratch spin"]),
    _node("fs1_step_intro", chapter="fs1", chapter_order=2, stage=2, group_name="后滑安全感", sort_order=5, name="步伐入门", emoji="🎵", xp=60, requires=["basic_all"], action_type="步法", unlock_config={"score": {"threshold": 60, "consecutive": 2, "action_type": "步法"}}, search_terms=["步伐入门", "步法入门"]),
    _node("fs1_waltz", chapter="fs1", chapter_order=2, stage=2, group_name="跳跃启蒙", sort_order=6, name="华尔兹跳", emoji="🌸", xp=100, requires=["basic_all"], action_type="跳跃", unlock_config={"score": {"threshold": 65, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["华尔兹跳", "waltz"]),
    _node("fs1_half_flip", chapter="fs1", chapter_order=2, stage=2, group_name="跳跃启蒙", sort_order=7, name="半翻转跳", emoji="🃏", xp=80, requires=["basic_all"], action_type="跳跃", unlock_config={"score": {"threshold": 65, "consecutive": 2, "action_type": "跳跃"}}, search_terms=["半翻转跳", "half flip"]),
    _node("fs2_bk_edges", chapter="fs2", chapter_order=3, stage=2, group_name="后滑安全感", sort_order=1, name="后外/后内连续刃", emoji="🛤️", xp=80, requires=["fs1_fwd_edges"], action_type="步法", unlock_config={"score": {"threshold": 62, "consecutive": 2, "action_type": "步法"}}, search_terms=["后外/后内连续刃", "后连续刃"]),
    _node("fs2_spirals", chapter="fs2", chapter_order=3, stage=2, group_name="弧线与延展", sort_order=2, name="前外/前内螺旋线", emoji="🦢", xp=80, requires=["fs1_stroking"], action_type="步法", unlock_config={"score": {"threshold": 62, "consecutive": 2, "action_type": "步法"}}, search_terms=["螺旋线", "前外/前内螺旋线"]),
    _node("fs2_waltz_three", chapter="fs2", chapter_order=3, stage=2, group_name="肩髋同步转体", sort_order=3, name="华尔兹三转弯", emoji="🔄", xp=80, requires=["fs1_bk_three_turn"], action_type="步法", unlock_config={"score": {"threshold": 62, "consecutive": 2, "action_type": "步法"}}, search_terms=["华尔兹三转弯", "waltz three"]),
    _node("fs2_backspin", chapter="fs2", chapter_order=3, stage=2, group_name="旋转发展", sort_order=4, name="后旋入门2圈", emoji="🌀", xp=120, requires=["fs1_spin_scratch"], action_type="旋转", unlock_config={"score": {"threshold": 65, "consecutive": 2, "action_type": "旋转"}}, search_terms=["后旋", "后旋入门"]),
    _node("fs2_step_chasse", chapter="fs2", chapter_order=3, stage=2, group_name="肩髋同步转体", sort_order=5, name="沙塞步伐序列", emoji="🎵", xp=80, requires=["fs1_step_intro"], action_type="步法", unlock_config={"score": {"threshold": 62, "consecutive": 2, "action_type": "步法"}}, search_terms=["沙塞步伐序列", "沙塞步伐"]),
    _node("fs2_toe", chapter="fs2", chapter_order=3, stage=2, group_name="跳跃巩固", sort_order=6, name="点冰跳", emoji="🐾", xp=100, requires=["fs1_waltz"], action_type="跳跃", unlock_config={"score": {"threshold": 65, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["点冰跳", "toe loop"]),
    _node("fs2_sal", chapter="fs2", chapter_order=3, stage=2, group_name="跳跃巩固", sort_order=7, name="萨霍夫跳", emoji="🌙", xp=100, requires=["fs1_waltz"], action_type="跳跃", unlock_config={"score": {"threshold": 65, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["萨霍夫跳", "salchow"]),
    _node("fs2_half_lutz", chapter="fs2", chapter_order=3, stage=2, group_name="跳跃巩固", sort_order=8, name="半勾手跳", emoji="⚔️", xp=80, requires=["fs2_toe"], action_type="跳跃", unlock_config={"score": {"threshold": 65, "consecutive": 2, "action_type": "跳跃"}}, search_terms=["半勾手跳", "half lutz"]),
    _node("fs2_combo_waltz_toe", chapter="fs2", chapter_order=3, stage=2, group_name="跳跃巩固", sort_order=9, name="华尔兹+点冰连跳", emoji="⚡", xp=150, requires=["fs1_waltz", "fs2_toe"], action_type="跳跃", unlock_config={"score": {"threshold": 65, "consecutive": 2, "action_type": "跳跃"}}, search_terms=["华尔兹+点冰连跳", "华尔兹点冰连跳"]),
    _node("fs3_crossover_fig8", chapter="fs3", chapter_order=4, stage=3, group_name="交叉与圆形步法", sort_order=1, name="前后交叉步8字", emoji="8️⃣", xp=100, requires=["fs2_bk_edges"], action_type="步法", unlock_config={"score": {"threshold": 65, "consecutive": 2, "action_type": "步法"}}, search_terms=["前后交叉步8字", "交叉步8字"]),
    _node("fs3_waltz_eight", chapter="fs3", chapter_order=4, stage=3, group_name="交叉与圆形步法", sort_order=2, name="华尔兹8字", emoji="🎭", xp=100, requires=["fs2_waltz_three"], action_type="步法", unlock_config={"score": {"threshold": 65, "consecutive": 2, "action_type": "步法"}}, search_terms=["华尔兹8字"]),
    _node("fs3_backspin_cross", chapter="fs3", chapter_order=4, stage=3, group_name="旋转组合", sort_order=3, name="后旋交叉腿3圈", emoji="🌀", xp=150, requires=["fs2_backspin"], action_type="旋转", unlock_config={"score": {"threshold": 68, "consecutive": 3, "action_type": "旋转"}}, search_terms=["后旋交叉腿3圈", "后旋交叉腿"]),
    _node("fs3_step_circle", chapter="fs3", chapter_order=4, stage=3, group_name="交叉与圆形步法", sort_order=4, name="圆圈步伐序列", emoji="🎵", xp=120, requires=["fs2_step_chasse"], action_type="步法", unlock_config={"score": {"threshold": 65, "consecutive": 2, "action_type": "步法"}}, search_terms=["圆圈步伐序列", "圆圈步伐"]),
    _node("fs3_combo_waltz_toe", chapter="fs3", chapter_order=4, stage=3, group_name="单跳进阶", sort_order=5, name="华尔兹+点冰序列", emoji="⚡", xp=200, requires=["fs2_sal", "fs2_toe"], action_type="跳跃", unlock_config={"score": {"threshold": 68, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["华尔兹+点冰序列", "华尔兹点冰序列"]),
    _node("fs4_spiral_seq", chapter="fs4", chapter_order=5, stage=3, group_name="交叉与圆形步法", sort_order=1, name="螺旋线序列", emoji="🦢", xp=120, requires=["fs3_crossover_fig8", "fs2_spirals"], action_type="步法", unlock_config={"score": {"threshold": 68, "consecutive": 2, "action_type": "步法"}}, search_terms=["螺旋线序列"]),
    _node("fs4_sit_spin", chapter="fs4", chapter_order=5, stage=3, group_name="旋转组合", sort_order=2, name="蹲转3圈", emoji="🪑", xp=200, requires=["fs3_backspin_cross"], action_type="旋转", unlock_config={"problem_gone": {"category": "重心偏移", "consecutive_clean": 3}}, search_terms=["蹲转3圈", "蹲转"]),
    _node("fs4_fwd_bk_spin", chapter="fs4", chapter_order=5, stage=3, group_name="旋转组合", sort_order=3, name="前旋转后旋", emoji="🌀", xp=200, requires=["fs3_backspin_cross"], action_type="旋转", unlock_config={"score": {"threshold": 70, "consecutive": 3, "action_type": "旋转"}}, search_terms=["前旋转后旋", "前旋后旋"]),
    _node("fs4_loop", chapter="fs4", chapter_order=5, stage=3, group_name="单跳进阶", sort_order=4, name="勾手跳", emoji="🔁", xp=150, requires=["fs2_toe"], action_type="跳跃", unlock_config={"score": {"threshold": 70, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["勾手跳", "loop"]),
    _node("fs4_flip", chapter="fs4", chapter_order=5, stage=3, group_name="单跳进阶", sort_order=5, name="翻转跳", emoji="🃏", xp=150, requires=["fs2_sal"], action_type="跳跃", unlock_config={"score": {"threshold": 70, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["翻转跳", "flip"]),
    _node("fs5_camel", chapter="fs5", chapter_order=6, stage=3, group_name="旋转组合", sort_order=1, name="燕式旋转3圈", emoji="🦅", xp=250, requires=["fs4_sit_spin"], action_type="旋转", unlock_config={"problem_gone": {"category": "重心偏移", "consecutive_clean": 3}}, search_terms=["燕式旋转3圈", "燕式旋转"]),
    _node("fs5_spin_combo", chapter="fs5", chapter_order=6, stage=3, group_name="旋转组合", sort_order=2, name="联合旋转", emoji="🌀", xp=200, requires=["fs4_fwd_bk_spin"], action_type="旋转", unlock_config={"score": {"threshold": 70, "consecutive": 3, "action_type": "旋转"}}, search_terms=["联合旋转", "spin combo"]),
    _node("fs5_lutz", chapter="fs5", chapter_order=6, stage=3, group_name="单跳进阶", sort_order=3, name="勾手外跳", emoji="⚔️", xp=200, requires=["fs4_flip"], action_type="跳跃", unlock_config={"score": {"threshold": 72, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["勾手外跳", "lutz"]),
    _node("fs5_loop_loop", chapter="fs5", chapter_order=6, stage=3, group_name="单跳进阶", sort_order=4, name="勾手+勾手连跳", emoji="🔁", xp=250, requires=["fs4_loop"], action_type="跳跃", unlock_config={"score": {"threshold": 72, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["勾手+勾手连跳", "loop loop"]),
    _node("fs6_camel_sit", chapter="fs6", chapter_order=7, stage=4, group_name="高级旋转", sort_order=1, name="燕转蹲转联合", emoji="🦅", xp=300, requires=["fs5_camel", "fs4_sit_spin"], action_type="旋转", unlock_config={"score": {"threshold": 72, "consecutive": 3, "action_type": "旋转"}}, search_terms=["燕转蹲转联合"]),
    _node("fs6_layback", chapter="fs6", chapter_order=7, stage=4, group_name="高级旋转", sort_order=2, name="仰身旋转", emoji="🌟", xp=350, requires=["fs5_spin_combo"], action_type="旋转", unlock_config={"problem_gone": {"category": "手臂松散", "consecutive_clean": 3}}, search_terms=["仰身旋转", "layback"]),
    _node("fs6_axel_prep", chapter="fs6", chapter_order=7, stage=4, group_name="Axel 与双跳", sort_order=3, name="Axel 预备", emoji="👑", xp=400, requires=["fs5_lutz"], action_type="跳跃", unlock_config={"score": {"threshold": 70, "consecutive": 2, "action_type": "跳跃"}}, search_terms=["axel 预备", "axel预备", "axel prep"]),
    _node("fs7_camel_sit_bk", chapter="fs7", chapter_order=8, stage=4, group_name="高级旋转", sort_order=1, name="燕转蹲转+换脚", emoji="🦅", xp=350, requires=["fs6_camel_sit"], action_type="旋转", unlock_config={"score": {"threshold": 75, "consecutive": 3, "action_type": "旋转"}}, search_terms=["燕转蹲转+换脚", "换脚燕转蹲转"]),
    _node("fs7_flying_spin", chapter="fs7", chapter_order=8, stage=4, group_name="高级旋转", sort_order=2, name="飞旋", emoji="🚀", xp=350, requires=["fs6_camel_sit"], action_type="旋转", unlock_config={"score": {"threshold": 75, "consecutive": 3, "action_type": "旋转"}}, search_terms=["飞旋", "flying spin"]),
    _node("fs7_axel", chapter="fs7", chapter_order=8, stage=4, group_name="Axel 与双跳", sort_order=3, name="Axel 1.5周", emoji="👑", xp=400, requires=["fs6_axel_prep"], action_type="跳跃", unlock_config={"score": {"threshold": 75, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["axel 1.5周", "axel", "阿克塞尔"]),
    _node("fs8_spin_4pos", chapter="fs8", chapter_order=9, stage=4, group_name="高级旋转", sort_order=1, name="四位置联合旋转", emoji="🌟", xp=400, requires=["fs7_camel_sit_bk", "fs6_layback"], action_type="旋转", unlock_config={"score": {"threshold": 78, "consecutive": 3, "action_type": "旋转"}}, search_terms=["四位置联合旋转"]),
    _node("fs8_2toe", chapter="fs8", chapter_order=9, stage=4, group_name="双跳竞技", sort_order=2, name="双周点冰跳", emoji="💎", xp=400, requires=["fs7_axel"], action_type="跳跃", unlock_config={"score": {"threshold": 78, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["双周点冰跳", "2toe"]),
    _node("fs8_2sal", chapter="fs8", chapter_order=9, stage=4, group_name="双跳竞技", sort_order=3, name="双周萨霍夫", emoji="💎", xp=400, requires=["fs7_axel"], action_type="跳跃", unlock_config={"score": {"threshold": 78, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["双周萨霍夫", "2sal"]),
    _node("fs8_2loop", chapter="fs8", chapter_order=9, stage=4, group_name="双跳竞技", sort_order=4, name="双周勾手跳", emoji="💎", xp=400, requires=["fs8_2toe"], action_type="跳跃", unlock_config={"score": {"threshold": 78, "consecutive": 3, "action_type": "跳跃"}}, search_terms=["双周勾手跳", "2loop"]),
    _node("fs9_2flip", chapter="fs9", chapter_order=10, stage=4, group_name="双跳竞技", sort_order=1, name="双周翻转", emoji="🃏", xp=500, requires=["fs8_2loop"], action_type="跳跃", unlock_config={"score": {"threshold": 80, "consecutive": 1, "action_type": "跳跃"}}, search_terms=["双周翻转", "2flip"]),
    _node("fs9_2lutz", chapter="fs9", chapter_order=10, stage=4, group_name="双跳竞技", sort_order=2, name="双周勾手外", emoji="⚔️", xp=500, requires=["fs8_2loop"], action_type="跳跃", unlock_config={"score": {"threshold": 80, "consecutive": 1, "action_type": "跳跃"}}, search_terms=["双周勾手外", "2lutz"]),
    _node("fs9_2axel", chapter="fs9", chapter_order=10, stage=4, group_name="Axel 与双跳", sort_order=3, name="双 Axel 2.5周", emoji="👑", xp=800, requires=["fs7_axel"], action_type="跳跃", unlock_config={"score": {"threshold": 82, "consecutive": 1, "action_type": "跳跃"}}, search_terms=["双 axel", "双Axel", "2axel"]),
    _node("fs10_3toe", chapter="fs10", chapter_order=11, stage=4, group_name="顶级目标", sort_order=1, name="三周点冰", emoji="🌈", xp=1000, is_parent_only=True, action_type="跳跃", search_terms=["三周点冰", "3toe"]),
    _node("fs10_3sal", chapter="fs10", chapter_order=11, stage=4, group_name="顶级目标", sort_order=2, name="三周萨霍夫", emoji="🌈", xp=1000, is_parent_only=True, action_type="跳跃", search_terms=["三周萨霍夫", "3sal"]),
    _node("fs10_3axel", chapter="fs10", chapter_order=11, stage=4, group_name="顶级目标", sort_order=3, name="三 Axel", emoji="🏆", xp=2000, is_parent_only=True, action_type="跳跃", search_terms=["三 axel", "三Axel", "3axel"]),
    _node("fs10_quad", chapter="fs10", chapter_order=11, stage=4, group_name="顶级目标", sort_order=4, name="四周跳", emoji="💫", xp=3000, is_parent_only=True, action_type="跳跃", search_terms=["四周跳", "quad"]),
]


def is_unlocked(status: str | None) -> bool:
    return status in UNLOCKED_STATUSES or status in {"unlocked_ai", "unlocked_parent"}


def avatar_level_for_xp(total_xp: int) -> int:
    level = 1
    for avatar_level, threshold, _, _ in LEVEL_THRESHOLDS:
        if total_xp >= threshold:
            level = avatar_level
    return level


def calculate_current_streak(dates: list[date]) -> int:
    if not dates:
        return 0
    unique_dates = sorted(set(dates), reverse=True)
    today = datetime.now(timezone.utc).date()
    if unique_dates[0] < today - timedelta(days=1):
        return 0

    streak = 1
    cursor = unique_dates[0]
    for current_date in unique_dates[1:]:
        if cursor - current_date == timedelta(days=1):
            streak += 1
            cursor = current_date
        else:
            break
    return streak


def calculate_longest_streak(dates: list[date]) -> int:
    if not dates:
        return 0
    unique_dates = sorted(set(dates))
    longest = 1
    streak = 1
    for previous, current in zip(unique_dates, unique_dates[1:]):
        if current - previous == timedelta(days=1):
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 1
    return longest


async def seed_skill_catalog() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SkillNode))
        existing = {node.id: node for node in result.scalars().all()}
        for payload in SKILL_CATALOG:
            node = existing.get(payload["id"])
            if node is None:
                session.add(SkillNode(**payload))
                continue
            for key, value in payload.items():
                setattr(node, key, value)
        await session.commit()


async def ensure_skater_skill_rows(session: AsyncSession, skater: Skater) -> None:
    nodes = list((await session.execute(select(SkillNode))).scalars().all())
    rows = list((await session.execute(select(SkaterSkill).where(SkaterSkill.skater_id == skater.id))).scalars().all())
    existing_rows = {row.skill_id: row for row in rows}
    for node in nodes:
        if node.id in existing_rows:
            if skater.name == "tantan" and node.id in {"ss_all", "basic_all"} and existing_rows[node.id].status == "locked":
                existing_rows[node.id].status = "unlocked"
                existing_rows[node.id].unlocked_by = "parent"
                existing_rows[node.id].unlocked_at = datetime.now(timezone.utc)
            continue
        initial_status = "locked"
        unlocked_at = None
        unlocked_by = None
        if skater.name == "tantan" and node.id in {"ss_all", "basic_all"}:
            initial_status = "unlocked"
            unlocked_by = "parent"
            unlocked_at = datetime.now(timezone.utc)
        session.add(
            SkaterSkill(
                skater_id=skater.id,
                skill_id=node.id,
                status=initial_status,
                unlocked_at=unlocked_at,
                unlocked_by=unlocked_by,
            )
        )
    await session.flush()


async def refresh_skater_skill_states(session: AsyncSession, skater_id: str) -> None:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        return

    await ensure_skater_skill_rows(session, skater)
    rows = list((await session.execute(select(SkaterSkill).where(SkaterSkill.skater_id == skater_id))).scalars().all())
    for row in rows:
        if row.status == "in_progress":
            row.status = "attempting"
        elif row.status in {"unlocked_ai", "unlocked_parent"}:
            row.status = "unlocked"

        if row.status == "unlocked":
            if row.unlocked_by is None:
                row.unlocked_by = "auto"
            if row.unlocked_at is None:
                row.unlocked_at = datetime.now(timezone.utc)
        else:
            row.unlocked_at = None
            if row.status == "locked":
                row.unlocked_by = None


async def refresh_skater_profile(session: AsyncSession, skater_id: str) -> None:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        return

    skill_rows = list((await session.execute(select(SkaterSkill).where(SkaterSkill.skater_id == skater_id))).scalars().all())
    nodes = {}
    if skill_rows:
        node_result = await session.execute(select(SkillNode).where(SkillNode.id.in_([row.skill_id for row in skill_rows])))
        nodes = {node.id: node for node in node_result.scalars().all()}

    total_xp = sum(nodes[row.skill_id].xp for row in skill_rows if is_unlocked(row.status) and row.skill_id in nodes)
    skater.total_xp = total_xp
    skater.avatar_level = avatar_level_for_xp(total_xp)

    analyses = list(
        (
            await session.execute(
                select(Analysis)
                .where(Analysis.skater_id == skater_id, Analysis.status == "completed")
                .order_by(Analysis.created_at.desc())
            )
        ).scalars().all()
    )
    active_dates = [
        (analysis.created_at.replace(tzinfo=timezone.utc) if analysis.created_at.tzinfo is None else analysis.created_at.astimezone(timezone.utc)).date()
        for analysis in analyses
    ]
    skater.current_streak = calculate_current_streak(active_dates)
    skater.longest_streak = calculate_longest_streak(active_dates)
    skater.last_active_date = active_dates[0].isoformat() if active_dates else None


async def sync_skater_progress(session: AsyncSession, skater_id: str) -> None:
    await refresh_skater_skill_states(session, skater_id)
    await refresh_skater_profile(session, skater_id)


async def sync_all_skater_progress() -> None:
    async with AsyncSessionLocal() as session:
        skaters = list((await session.execute(select(Skater))).scalars().all())
        for skater in skaters:
            await sync_skater_progress(session, skater.id)
        await session.commit()


def serialize_skill(node: SkillNode, row: SkaterSkill) -> dict[str, Any]:
    unlock_config = node.unlock_config if isinstance(node.unlock_config, dict) else None
    score_unlock_config = unlock_config
    if unlock_config is not None and isinstance(unlock_config.get("score"), dict):
        score_unlock_config = unlock_config["score"]
    return {
        "id": node.id,
        "chapter": node.chapter,
        "chapter_order": node.chapter_order,
        "stage": node.stage,
        "stage_name": node.stage_name,
        "group_name": node.group_name,
        "name": node.name,
        "emoji": node.emoji,
        "action_type": node.action_type,
        "xp": node.xp,
        "requires": node.requires or [],
        "status": row.status,
        "attempt_count": row.attempt_count,
        "best_score": row.best_score,
        "unlocked_by": row.unlocked_by,
        "unlock_config": score_unlock_config,
        "is_parent_only": node.is_parent_only,
        "unlocked_at": row.unlocked_at,
        "unlock_source": row.unlocked_by,
        "unlock_note": row.unlock_note,
    }


async def get_skater_skill_payloads(session: AsyncSession, skater_id: str) -> list[dict[str, Any]]:
    await sync_skater_progress(session, skater_id)
    nodes = list(
        (
            await session.execute(select(SkillNode).order_by(SkillNode.chapter_order.asc(), SkillNode.sort_order.asc()))
        ).scalars().all()
    )
    rows = {
        row.skill_id: row
        for row in (await session.execute(select(SkaterSkill).where(SkaterSkill.skater_id == skater_id))).scalars().all()
    }
    return [serialize_skill(node, rows[node.id]) for node in nodes if node.id in rows]


async def unlock_skill(
    session: AsyncSession,
    skater_id: str,
    skill_id: str,
    source: str = "parent",
    note: str | None = None,
) -> dict[str, Any]:
    node = await session.get(SkillNode, skill_id)
    if node is None:
        raise ValueError("技能节点不存在。")
    row_result = await session.execute(
        select(SkaterSkill).where(SkaterSkill.skater_id == skater_id, SkaterSkill.skill_id == skill_id).limit(1)
    )
    row = row_result.scalar_one_or_none()
    if row is None:
        raise ValueError("该选手尚未初始化技能树。")
    row.status = "unlocked"
    row.unlocked_by = source
    row.unlocked_at = datetime.now(timezone.utc)
    row.unlock_note = (note or "").strip() or None
    await refresh_skater_profile(session, skater_id)
    await session.flush()
    return serialize_skill(node, row)


async def lock_skill(session: AsyncSession, skater_id: str, skill_id: str) -> dict[str, Any]:
    node = await session.get(SkillNode, skill_id)
    if node is None:
        raise ValueError("技能节点不存在。")
    row_result = await session.execute(
        select(SkaterSkill).where(SkaterSkill.skater_id == skater_id, SkaterSkill.skill_id == skill_id).limit(1)
    )
    row = row_result.scalar_one_or_none()
    if row is None:
        raise ValueError("该选手尚未初始化技能树。")
    row.status = "locked"
    row.attempt_count = 0
    row.unlocked_by = None
    row.unlocked_at = None
    row.unlock_note = None
    await sync_skater_progress(session, skater_id)
    await session.flush()
    return serialize_skill(node, row)


async def build_learning_path(session: AsyncSession, skater_id: str) -> dict[str, Any]:
    skills = await get_skater_skill_payloads(session, skater_id)
    stages_map: dict[int, dict[str, Any]] = {}
    for stage_number, definition in STAGE_DEFINITIONS.items():
        stages_map[stage_number] = {
            "stage": stage_number,
            "name": definition["name"],
            "description": definition["description"],
            "progress_pct": 0,
            "counts": {"locked": 0, "attempting": 0, "unlocked": 0},
            "groups": [],
        }

    groups_by_stage: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for skill in skills:
        groups_by_stage[skill["stage"]][skill["group_name"]].append(skill)
        if skill["status"] in UNLOCKED_STATUSES:
            stages_map[skill["stage"]]["counts"]["unlocked"] += 1
        elif skill["status"] == "attempting":
            stages_map[skill["stage"]]["counts"]["attempting"] += 1
        else:
            stages_map[skill["stage"]]["counts"]["locked"] += 1

    for stage_number, groups in groups_by_stage.items():
        total = sum(len(nodes) for nodes in groups.values())
        unlocked_total = sum(sum(1 for node in nodes if node["status"] in UNLOCKED_STATUSES) for nodes in groups.values())
        stages_map[stage_number]["progress_pct"] = round((unlocked_total / total) * 100) if total else 0
        stages_map[stage_number]["groups"] = [
            {
                "group_name": group_name,
                "nodes_total": len(nodes),
                "nodes_unlocked": sum(1 for node in nodes if node["status"] in UNLOCKED_STATUSES),
                "nodes": nodes,
            }
            for group_name, nodes in groups.items()
        ]

    stages = [stages_map[index] for index in sorted(stages_map)]
    current_stage = next((stage["stage"] for stage in stages if stage["progress_pct"] < 100), stages[-1]["stage"])
    return {"stages": stages, "current_stage": current_stage}
