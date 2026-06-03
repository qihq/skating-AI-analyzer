from __future__ import annotations


CURRENT_PIPELINE_VERSION = "v5.2.11"

# v1.1.1: Add manual target bbox lock and per-frame bbox tracking for pose extraction.
# v1.1.2: Pass effective sampling fps into biomechanics to correct slow-motion jump metrics.
# v1.1.3: Unwrap shoulder rotation angles before estimating jump rotation speed.
# v1.1.4: Retry transient AI provider failures and degrade vision/report output when AI is unavailable.
# v1.1.5: Add video prechecks and no-person target preview status before pose/LLM analysis.
# v1.1.6: Smooth pose keypoints with One-Euro filtering and interpolate short low-visibility gaps.
# v1.1.7: Add geometric jump subtype evidence for Lutz/Flip and inject it into vision prompts.
# v1.1.8: Add Qwen-VL native action-window video mode with frame-mode fallback.
# v1.1.9: Drive profile sampling density from config and protect motion peak neighborhoods.
# v1.1.10: Add frame-mode self-consistency voting and key-frame phase overrides.
# v1.1.11: Add multi-provider Qwen/Doubao vision voting and Doubao video slot validation.
# v5.0.0: Add Qwen 3.6 Plus video temporal localization, semantic keyframe arbitration, semantic FFmpeg extraction, image AI video_context, and video/image/MediaPipe report fusion.
# v5.1.0: Add Pose Debug replay page, responsive PWA-safe debug UI, and separate pose/YOLO runtime checks.
# v5.2.0: Align debug replay with the formal sampling pipeline and exclude unreliable pose frames from keyframe scoring.
# v5.2.1: Tighten jump action-window padding and anchor target preview on high-motion sampled frames.
# v5.2.2: Preserve tracker-aligned crop poses during fast target motion instead of over-penalizing seed-bbox drift.
# v5.2.3: Let pose extraction use unconfirmed-but-gated tracker relock boxes as crop hints without switching target identity.
# v5.2.4: Keep ordered visible T/A/L candidates complete while preserving low-confidence keyframe warnings.
# v5.2.5: Validate regular pose crops against their actual reference bbox when motion-predicted crops are also attempted.
# v5.2.6: Reuse overlap-safe continuity-rejected tracker boxes as pose crop hints without accepting target identity changes.
# v5.2.7: Apply tracker-style crop padding to overlap-safe rejected tracker hints even when they become the reference bbox.
# v5.2.8: Treat reused lost tracker boxes as padded pose crop hints for distant tiny skaters.
# v5.2.9: Recover malformed Path A JSON and ground report issues/improvements in Path B evidence when Path A is unavailable.
# v5.2.10: Stop startup AI provider seeding so legacy duplicate provider rows cannot block container startup.
# v5.2.11: Use full video context by default, expose manual input windows, and require manual target selection for review-flagged multi-person locks.
