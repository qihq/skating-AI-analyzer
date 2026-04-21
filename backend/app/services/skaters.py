from __future__ import annotations

from sqlalchemy import or_, select

from app.database import AsyncSessionLocal
from app.models import Skater
from app.services.snowball import seed_default_memories_for_skater


PRESET_SKATERS = [
    {
        "name": "tantan",
        "legacy_names": [],
        "display_name": "坦坦",
        "avatar_type": "zodiac_rat",
        "avatar_emoji": "🐭",
        "birth_year": 2020,
        "current_level": "fs1",
        "level": "一级自由滑",
        "notes": "6岁，主训练账号",
        "is_default": True,
    },
    {
        "name": "zhaozao",
        "legacy_names": ["didi"],
        "display_name": "昭昭",
        "avatar_type": "zodiac_tiger",
        "avatar_emoji": "🐯",
        "birth_year": 2022,
        "current_level": "snowplow",
        "level": "启蒙训练",
        "notes": "4岁，家庭练习记录",
        "is_default": False,
    },
]


async def seed_preset_skaters() -> None:
    async with AsyncSessionLocal() as session:
        existing_result = await session.execute(select(Skater).order_by(Skater.created_at.asc()))
        existing_skaters = list(existing_result.scalars().all())

        for preset in PRESET_SKATERS:
            candidate_names = [preset["name"], *preset.get("legacy_names", [])]
            result = await session.execute(
                select(Skater)
                .where(or_(Skater.name.in_(candidate_names), Skater.display_name == preset["display_name"]))
                .limit(1)
            )
            skater = result.scalar_one_or_none()
            if skater is None:
                skater = next(
                    (
                        candidate
                        for candidate in existing_skaters
                        if candidate.name in {*candidate_names, preset["display_name"]}
                        or candidate.display_name == preset["display_name"]
                    ),
                    None,
                )
            if skater is None:
                skater = Skater()
                session.add(skater)

            skater.name = preset["name"]
            skater.display_name = preset["display_name"]
            skater.avatar_type = preset["avatar_type"]
            skater.avatar_emoji = preset["avatar_emoji"]
            skater.birth_year = preset["birth_year"]
            skater.current_level = preset["current_level"]
            skater.level = preset["level"]
            skater.notes = preset["notes"]
            skater.is_default = preset["is_default"]
            await session.flush()
            await seed_default_memories_for_skater(session, skater)

        await session.commit()
