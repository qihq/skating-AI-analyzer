from __future__ import annotations


CURRENT_PIPELINE_VERSION = "v1.1.10"

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
