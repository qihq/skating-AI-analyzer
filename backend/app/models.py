from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    slot: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40), index=True)
    base_url: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(120))
    vision_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    api_key: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    skater_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("training_sessions.id"), nullable=True)
    skill_node_id: Mapped[str | None] = mapped_column(String(80), ForeignKey("skill_nodes.id"), nullable=True)
    skill_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    video_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    vision_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    vision_structured: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pose_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    bio_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    frame_motion_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    action_window_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_window_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_slow_motion: Mapped[bool] = mapped_column(Boolean, default=False)
    force_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_unlocked_skill: Mapped[str | None] = mapped_column(String(80), ForeignKey("skill_nodes.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    session: Mapped["TrainingSession | None"] = relationship("TrainingSession", back_populates="analyses")


class TrainingSession(Base):
    __tablename__ = "training_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    skater_id: Mapped[str] = mapped_column(String(36), ForeignKey("skaters.id"), index=True)
    session_date: Mapped[date] = mapped_column()
    location: Mapped[str] = mapped_column(String(40), default="冰场")
    session_type: Mapped[str] = mapped_column(String(20), default="上冰")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coach_present: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    analyses: Mapped[list["Analysis"]] = relationship("Analysis", back_populates="session")


class Skater(Base):
    __tablename__ = "skaters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(80), index=True, unique=True)
    display_name: Mapped[str] = mapped_column(String(80), default="")
    avatar_emoji: Mapped[str] = mapped_column(String(12), default="⛸️")
    avatar_type: Mapped[str] = mapped_column(String(24), default="emoji")
    birth_year: Mapped[int] = mapped_column(Integer, default=2021)
    current_level: Mapped[str] = mapped_column(String(40), default="snowplow")
    avatar_level: Mapped[int] = mapped_column(Integer, default=1)
    total_xp: Mapped[int] = mapped_column(Integer, default=0)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    level: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class TrainingPlan(Base):
    __tablename__ = "training_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    analysis_id: Mapped[str] = mapped_column(String(36), index=True, unique=True)
    skater_id: Mapped[str] = mapped_column(String(36), index=True)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParentAuth(Base):
    __tablename__ = "parent_auth"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pin_hash: Mapped[str] = mapped_column(Text)
    pin_length: Mapped[int] = mapped_column(Integer, default=4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SkillNode(Base):
    __tablename__ = "skill_nodes"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    chapter: Mapped[str] = mapped_column(String(40), index=True)
    chapter_order: Mapped[int] = mapped_column(Integer, index=True)
    stage: Mapped[int] = mapped_column(Integer, index=True)
    stage_name: Mapped[str] = mapped_column(String(80))
    group_name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(12), default="⛸️")
    action_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    unlock_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    requires: Mapped[list[str]] = mapped_column(JSON, default=list)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    is_parent_only: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class SkaterSkill(Base):
    __tablename__ = "skater_skills"
    __table_args__ = (UniqueConstraint("skater_id", "skill_id", name="uq_skater_skill"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    skater_id: Mapped[str] = mapped_column(String(36), index=True)
    skill_id: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24), default="locked", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[int] = mapped_column(Integer, default=0)
    unlocked_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    unlock_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class SnowballMemory(Base):
    __tablename__ = "snowball_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    skater_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), default="其他")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class MemorySuggestion(Base):
    __tablename__ = "memory_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), index=True)
    skater_id: Mapped[str] = mapped_column(String(36), ForeignKey("skaters.id"), index=True)
    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
