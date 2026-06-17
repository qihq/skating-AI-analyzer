from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError


TARGET_LOCK_AUTO_THRESHOLD = 0.72
TARGET_LOCK_STABLE_ZOOMED_AUTO_THRESHOLD = 0.68
TARGET_LOCK_STABLE_ZOOMED_MIN_SUPPORT = 5
TARGET_LOCK_STABLE_ZOOMED_MAX_AREA = 0.04
TARGET_LOCK_STABLE_ZOOMED_NEAR_THRESHOLD = 0.70
TARGET_LOCK_STABLE_ZOOMED_NEAR_MIN_SUPPORT = 8
TARGET_LOCK_STABLE_ZOOMED_NEAR_MAX_AREA = 0.12
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_THRESHOLD = 0.78
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_SUPPORT = 8
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_UNIQUE_FRAMES = 5
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MAX_AREA = 0.018
TARGET_LOCK_TINY_ZOOMED_MANUAL_REVIEW_MAX_AREA = 0.012
TARGET_LOCK_TINY_ZOOMED_MIN_SUPPORT_CONFIDENCE = 0.65
TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_SUPPORT = 3
TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_UNIQUE_FRAMES = 2
TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_CONFIDENCE = 0.40
TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_SUPPORT_CONFIDENCE = 0.55
TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_AREA = 0.010
TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_COMPETITOR_CONFIDENCE = 0.35
TARGET_PERSON_MIN_CONFIDENCE = 0.15
MANUAL_BBOX_MIN_SIDE = 0.02
FALLBACK_TARGET_CONFIDENCE = 0.22
TARGET_PREVIEW_ANCHOR_FRACTIONS = (0.50, 0.42, 0.58, 0.35, 0.65, 0.25, 0.75)
TARGET_PREVIEW_CENTER_DISTANCE = 0.22
TARGET_PREVIEW_AREA_RATIO_RANGE = (0.20, 5.0)
TARGET_PREVIEW_ZOOMED_CENTER_DISTANCE = 0.18
TARGET_PREVIEW_ZOOMED_SIZE_MISMATCH_CENTER_DISTANCE = 0.12
TARGET_PREVIEW_ZOOMED_SIZE_MISMATCH_AREA_RATIO = 3.0
TARGET_PREVIEW_ZOOMED_TINY_AREA = 0.003
TARGET_PREVIEW_ZOOMED_TINY_TO_PERSON_AREA = 0.006
TARGET_LOCK_TINY_STABLE_MAX_AREA = 0.012
TARGET_LOCK_COMPLETE_BODY_MIN_AREA = 0.045
TARGET_LOCK_COMPLETE_BODY_MAX_AREA = 0.18
TARGET_LOCK_COMPLETE_BODY_MIN_HEIGHT = 0.35
TARGET_LOCK_COMPLETE_BODY_MIN_WIDTH = 0.07
TARGET_LOCK_COMPLETE_BODY_CONFIDENCE_ADVANTAGE = 0.15
TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CONFIDENCE = 0.55
TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CENTER_DISTANCE = 0.08
TARGET_LOCK_ZOOMED_MULTIPERSON_DUPLICATE_MIN_IOU = 0.45
TARGET_LOCK_ZOOMED_MULTIPERSON_DUPLICATE_MIN_CONTAINMENT = 0.68
TARGET_LOCK_ZOOMED_MULTIPERSON_DUPLICATE_MAX_AREA_RATIO = 3.2
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT = 24
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT_FRAMES = 8
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT_CONFIDENCE = 0.80
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_SELECTED_PAIR_FRAMES = 1
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_SAME_ANCHOR_COMPETITORS = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_AREA = 0.018
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_SUPPORT = 21
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_SUPPORT_FRAMES = 8
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_SUPPORT_CONFIDENCE = 0.84
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_MOTION_HITS = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MAX_CENTER_SPAN = 0.24
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_OTHER_FRAMES = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MODERATE_AUTO_MIN_SUPPORT = 22
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MODERATE_AUTO_MIN_SUPPORT_FRAMES = 9
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MODERATE_AUTO_MIN_SUPPORT_CONFIDENCE = 0.78
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT = 18
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT_FRAMES = 9
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT_CONFIDENCE = 0.84
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_RELAXED_MIN_CONFIDENCE = 0.835
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MAX_AREA = 0.045
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MAX_CENTER_SPAN = 0.25
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_DENSE_MIN_SUPPORT = 40
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_DENSE_MIN_CONFIDENCE = 0.77
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_DENSE_MAX_CENTER_SPAN = 0.32
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MIN_SUPPORT = 42
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MIN_CONFIDENCE = 0.86
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MAX_AREA = 0.045
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MAX_CENTER_SPAN = 0.42
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_AREA = 0.022
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_CENTER_SPAN = 0.20
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_OTHER_FRAMES = 5
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_COMPETITORS = 12
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DENSE_MOVING_RISK_MIN_CENTER_SPAN = 0.28
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DENSE_MOVING_RISK_MIN_OTHER_FRAMES = 5
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DENSE_MOVING_RISK_MIN_COMPETITORS = 12
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_AREA = 0.035
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_WIDTH = 0.10
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_HEIGHT = 0.24
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_CONFIDENCE = 0.86
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_SUPPORT = 18
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_SUPPORT_FRAMES = 9
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_SUPPORT_CONFIDENCE = 0.80
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_AREA_RATIO = 8.0
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_HEIGHT_RATIO = 2.4
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_AREA = 0.12
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_WIDTH = 0.18
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_HEIGHT = 0.40
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_CONFIDENCE = 0.88
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_SUPPORT = 16
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_SUPPORT_FRAMES = 9
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_SUPPORT_CONFIDENCE = 0.80
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MAX_OTHER_FRAMES = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MAX_COMPETITORS = 4
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_AREA = 0.045
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_AREA = 0.14
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_SUPPORT = 18
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_SUPPORT_FRAMES = 9
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_SUPPORT_CONFIDENCE = 0.86
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_CENTER_SPAN = 0.36
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_OTHER_FRAMES = 1
TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_COMPETITORS = 4
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_AREA = 0.022
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_AREA = 0.035
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_CONFIDENCE = 0.92
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_SUPPORT = 22
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_SUPPORT_FRAMES = 11
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_SUPPORT_CONFIDENCE = 0.83
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_CENTER_SPAN = 0.26
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_OTHER_FRAMES = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_COMPETITORS = 6
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_AREA = 0.020
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_AREA = 0.045
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_CONFIDENCE = 0.91
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_SUPPORT = 18
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_SUPPORT_FRAMES = 9
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_SUPPORT_CONFIDENCE = 0.82
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_CENTER_SPAN = 0.27
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_CENTER_DISTANCE = 0.16
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_OTHER_FRAMES = 4
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_COMPETITORS = 10
TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_AREA = 0.026
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_AREA = 0.036
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_WIDTH = 0.10
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_WIDTH = 0.14
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_HEIGHT = 0.22
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_HEIGHT = 0.30
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_CONFIDENCE = 0.91
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_SUPPORT = 24
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_SUPPORT_FRAMES = 11
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_SUPPORT_CONFIDENCE = 0.84
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_CENTER_SPAN = 0.28
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_OTHER_FRAMES = 5
TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_COMPETITORS = 12
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_AREA = 0.018
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_AREA = 0.040
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_CONFIDENCE = 0.92
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SUPPORT = 24
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SUPPORT_FRAMES = 10
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SUPPORT_CONFIDENCE = 0.88
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_OTHER_FRAMES = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_COMPETITORS = 6
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_CENTER_DISTANCE = 0.20
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SELECTED_PAIR_DISTANCE = 0.18
TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_SAME_ANCHOR_COMPETITORS = 0
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MAX_AREA = 0.018
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_CENTER_SPAN = 0.20
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_OTHER_FRAMES = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_SUPPORT_CONFIDENCE = 0.82
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_COMPETITORS = 40
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_SUPPORT = 30
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_SUPPORT_FRAMES = 10
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_SUPPORT_CONFIDENCE = 0.74
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MAX_CENTER_SPAN = 0.26
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_MOTION_HITS = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MAX_OTHER_FRAMES = 3
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MAX_COMPETITORS = 10
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MAX_AREA = 0.0085
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MAX_HEIGHT = 0.105
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MIN_CENTER_SPAN = 0.25
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MIN_OTHER_FRAMES = 5
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MIN_COMPETITORS = 24
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MAX_SUPPORT_CONFIDENCE = 0.85
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MAX_AREA = 0.012
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MIN_CENTER_SPAN = 0.32
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MIN_OTHER_FRAMES = 5
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MIN_COMPETITORS = 12
TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MAX_SUPPORT_CONFIDENCE = 0.84
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SELECTED_AREA = 0.024
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SELECTED_HEIGHT = 0.28
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_AREA = 0.006
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_HEIGHT = 0.12
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_AREA_RATIO = 0.70
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_HEIGHT_RATIO = 0.70
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SUPPORT = 8
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SUPPORT_RATIO = 0.75
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_SUPPORT_FRAME_GAP = 2
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SUPPORT_CONFIDENCE = 0.74
TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_SUPPORT_CONFIDENCE_GAP = 0.08
TARGET_LOCK_ZOOMED_FRAGMENT_MAX_AREA = 0.0045
TARGET_LOCK_ZOOMED_FRAGMENT_MAX_AREA_RATIO = 0.35
TARGET_LOCK_ZOOMED_FRAGMENT_MIN_TOP_SUPPORT_FRAMES = 5
TARGET_LOCK_ZOOMED_FRAGMENT_MIN_TOP_SUPPORT_CONFIDENCE = 0.74
TARGET_LOCK_ZOOMED_FRAGMENT_MIN_CONFIDENCE_ADVANTAGE = 0.08
TARGET_LOCK_ZOOMED_FOREGROUND_DEPRIORITIZE_MIN_AREA = 0.05
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_CONTEXT_MIN_AREA = 0.035
TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_AREA = 0.0015
TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MAX_AREA = 0.012
TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_HEIGHT = 0.08
TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_SUPPORT_FRAMES = 6
TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_SUPPORT_CONFIDENCE = 0.70
TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_MOTION_HITS = 2
TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_CENTER_DISTANCE = 0.08
TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_SUPPORT = 10
TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_SUPPORT_CONFIDENCE = 0.52
TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_AREA_RATIO = 20.0
TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_SUPPORT_FRAMES = 5
TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_HEIGHT = 0.08
TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_MIN_AMBIGUOUS_FRAMES = 2
TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_MIN_COMPETITORS = 2
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_AREA = 0.012
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MAX_AREA = 0.036
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_HEIGHT = 0.16
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MAX_WIDTH = 0.14
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_SUPPORT = 12
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_SUPPORT_FRAMES = 5
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_SUPPORT_CONFIDENCE = 0.72
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MAX_CENTER_SPAN = 0.46
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_AREA_RATIO = 1.25
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_HEIGHT_RATIO = 1.25
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_CONTEXT_MIN_AMBIGUOUS_FRAMES = 4
TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_CONTEXT_MIN_COMPETITORS = 8
TARGET_LOCK_ZOOMED_FOREGROUND_DEPRIORITIZE_PENALTY = 1.25
TARGET_LOCK_SUPPORT_FRAME_LIST_LIMIT = 12
TARGET_LOCK_MOTION_ANCHOR_TOP_N = 3
TARGET_LOCK_AGGREGATE_CANDIDATE_MIN_SUPPORT_FRAMES = 6
TARGET_LOCK_AGGREGATE_CANDIDATE_MIN_SUPPORT_CONFIDENCE = 0.74
TARGET_LOCK_AGGREGATE_CANDIDATE_MAX_AREA = 0.018
TARGET_LOCK_AGGREGATE_CANDIDATE_BONUS = 0.45
TARGET_LOCK_AGGREGATE_CANDIDATE_MIN_HEIGHT = 0.14
TARGET_LOCK_AGGREGATE_CANDIDATE_MAX_CENTER_SPAN = 0.32
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_SUPPORT_ADVANTAGE = 8
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_CONFIDENCE_ADVANTAGE = 0.03
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MAX_SUPPORT_CONFIDENCE_GAP = 0.04
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_AREA_RATIO = 0.65
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MAX_AREA_RATIO = 1.85
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_HEIGHT_RATIO = 0.75
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MAX_HEIGHT_RATIO = 1.85
TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_PENALTY = 0.50
TARGET_LOCK_PARTIAL_ZOOMED_BODY_MAX_AREA = 0.0032
TARGET_LOCK_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_AREA = 0.0085
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_AREA = 0.0032
TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_AREA = 0.018
TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_AREA = 0.026
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_HEIGHT = 0.115
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_FRAMES = 5
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_CONFIDENCE = 0.72
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_AREA_RATIO = 1.6
TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MIN_AREA_RATIO = 2.6
TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_CENTER_DISTANCE = 0.085
TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_SUPPORT_CENTER_SPAN = 0.40
TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_SUPPORT_CENTER_SPAN_ADVANTAGE = 0.10
TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_SUPPORT_CONFIDENCE_GAP = 0.04
TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_SUPPORT_CONFIDENCE_GAP = 0.10
TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MIN_CONFIDENCE_ADVANTAGE = 0.08
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_COMPETITOR_RISK_SUPPORT_RATIO = 1.25
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_COMPETITOR_RISK_SUPPORT_CONFIDENCE_ADVANTAGE = 0.02
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_MOTION_ANCHOR_HITS = 2
TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_RATIO = 0.85
TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_EXTRA_SAME_ANCHOR_COMPETITORS = 3
TARGET_LOCK_REVIEW_FOREGROUND_MIN_AREA = 0.024
TARGET_LOCK_REVIEW_FOREGROUND_MIN_HEIGHT = 0.30
TARGET_LOCK_REVIEW_FOREGROUND_MIN_WIDTH = 0.07
TARGET_LOCK_REVIEW_FOREGROUND_MIN_CONFIDENCE = 0.88
TARGET_LOCK_REVIEW_FOREGROUND_MIN_AREA_RATIO = 5.0
TARGET_LOCK_REVIEW_FOREGROUND_MIN_HEIGHT_RATIO = 2.5
TARGET_LOCK_REVIEW_FOREGROUND_MAX_SELECTED_PAIR_FRAMES = 1
TARGET_LOCK_REVIEW_BACKGROUND_RISK_MAX_AREA = 0.006
TARGET_LOCK_REVIEW_BACKGROUND_RISK_MAX_HEIGHT = 0.16
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_AREA = 0.020
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_AREA = 0.040
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_HEIGHT = 0.26
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_ASPECT_RATIO = 0.45
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_CONFIDENCE = 0.85
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_SUPPORT = 8
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_SUPPORT_FRAMES = 5
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_SUPPORT_CONFIDENCE = 0.72
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_AMBIGUOUS_FRAMES = 2
TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_SELECTED_PAIR_FRAMES = 1
TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_HEIGHT = 0.18
TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_WIDTH = 0.07
TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_ASPECT_RATIO = 0.32
TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_AREA_RATIO = 0.55
TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_SUPPORT_FRAMES = 5
TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_SUPPORT_GAP = 2
TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_SUPPORT_FRAME_GAP = 3
TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_SUPPORT_CONFIDENCE_ADVANTAGE = 0.03
TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_CONFIDENCE_GAP = 0.02
TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_MOTION_HIT_GAP = 1
TARGET_LOCK_REVIEW_TALL_MULTIPERSON_MIN_HEIGHT = 0.28
TARGET_LOCK_REVIEW_TALL_MULTIPERSON_MAX_WIDTH = 0.085
TARGET_LOCK_REVIEW_TALL_MULTIPERSON_MAX_ASPECT_RATIO = 0.32
TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_AREA = 0.008
TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_WIDTH = 0.045
TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_HEIGHT = 0.15
TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_AREA_RATIO = 0.90
TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_HEIGHT_RATIO = 0.76
TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_CENTER_DISTANCE = 0.055
TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_SUPPORT_ADVANTAGE = 2
TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_SUPPORT_FRAME_GAP = 1
TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_SUPPORT_CONFIDENCE_ADVANTAGE = 0.06
TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_CONFIDENCE_GAP = 0.10
TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_MOTION_HITS = 2
TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_CENTER_DISTANCE = 0.08


@dataclass(slots=True)
class TargetPreview:
    preview_frame: str | None
    preview_frame_url: str | None
    preview_frame_index: int | None
    auto_candidate_id: str | None
    lock_confidence: float
    candidates: list[dict[str, Any]]
    target_lock_status: str


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _normalized_bbox(x: float, y: float, width: float, height: float) -> dict[str, float]:
    return {
        "x": round(_clamp(x, 0.0, 1.0), 4),
        "y": round(_clamp(y, 0.0, 1.0), 4),
        "width": round(_clamp(width, MANUAL_BBOX_MIN_SIDE, 1.0), 4),
        "height": round(_clamp(height, MANUAL_BBOX_MIN_SIDE, 1.0), 4),
    }


def validate_manual_bbox(bbox: dict[str, Any] | None) -> dict[str, float]:
    """校验并标准化前端手动框选的主目标 bbox。

    Args:
        bbox: 前端传入的归一化 bbox，支持 width/height 或 w/h 字段。

    Returns:
        标准化后的 bbox，字段为 x/y/width/height。

    Raises:
        AnalysisPipelineError: bbox 缺字段、越界或尺寸过小时抛出 TARGET_BBOX_INVALID。
    """
    if not isinstance(bbox, dict):
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox must be an object.")

    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        width = float(bbox.get("width", bbox.get("w")))
        height = float(bbox.get("height", bbox.get("h")))
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox requires x/y/w/h values.") from exc

    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= width <= 1.0 and 0.0 <= height <= 1.0):
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox values must be normalized to 0-1.")
    if width < MANUAL_BBOX_MIN_SIDE or height < MANUAL_BBOX_MIN_SIDE:
        raise AnalysisPipelineError(
            AnalysisErrorCode.TARGET_BBOX_INVALID,
            f"manual_bbox width and height must be at least {MANUAL_BBOX_MIN_SIDE}.",
        )
    if x + width > 1.0 or y + height > 1.0:
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox must stay inside the frame.")

    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "width": round(width, 4),
        "height": round(height, 4),
    }


def _fallback_candidates(frame_names: Sequence[str]) -> list[dict[str, Any]]:
    if not frame_names:
        return []
    return [
        {
            "id": "fallback_center",
            "bbox": _normalized_bbox(0.40, 0.24, 0.20, 0.42),
            "confidence": FALLBACK_TARGET_CONFIDENCE,
            "source": "layout_fallback",
        }
    ]


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("id") or "").strip()


def _merge_strings(*sources: Sequence[Any]) -> list[str]:
    merged: list[str] = []
    for source in sources:
        for item in source:
            value = str(item).strip()
            if value and value not in merged:
                merged.append(value)
    return merged


def _has_manual_review_flag(candidate: dict[str, Any]) -> bool:
    flags = candidate.get("quality_flags")
    if not isinstance(flags, list):
        return False
    return any("_manual_review" in str(flag) for flag in flags)


def _is_confirmed_existing_lock(target_lock: dict[str, Any] | None) -> bool:
    if not isinstance(target_lock, dict):
        return False
    status = str(target_lock.get("status") or "")
    if status in {"locked", "manual"}:
        return True
    if status == "auto_locked":
        return isinstance(target_lock.get("selected_bbox"), dict) and not _has_manual_review_flag(target_lock)
    return False


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float]:
    try:
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    bbox = candidate.get("bbox")
    area = _bbox_area(bbox) if isinstance(bbox, dict) else 0.0
    return confidence, area


def _candidate_int_metric(candidate: dict[str, Any], name: str) -> int:
    try:
        return int(candidate.get(name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _candidate_float_metric(candidate: dict[str, Any], name: str) -> float:
    try:
        return float(candidate.get(name, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _aggregate_candidate_rank_bonus(
    candidate: dict[str, Any],
    *,
    support_frame_count: float,
    support_confidence: float,
    area: float,
    height: float,
    support_center_span: float | None,
) -> float:
    if (
        _candidate_id(candidate) != "candidate_auto_stable"
        or str(candidate.get("source") or "") != "yolo_zoomed_content"
        or support_frame_count < TARGET_LOCK_AGGREGATE_CANDIDATE_MIN_SUPPORT_FRAMES
        or support_confidence < TARGET_LOCK_AGGREGATE_CANDIDATE_MIN_SUPPORT_CONFIDENCE
        or area <= 0.0
        or area > TARGET_LOCK_AGGREGATE_CANDIDATE_MAX_AREA
    ):
        return 0.0

    fuller_target = height >= TARGET_LOCK_AGGREGATE_CANDIDATE_MIN_HEIGHT
    stable_support_path = (
        support_center_span is not None
        and support_center_span <= TARGET_LOCK_AGGREGATE_CANDIDATE_MAX_CENTER_SPAN
    )
    return TARGET_LOCK_AGGREGATE_CANDIDATE_BONUS if fuller_target or stable_support_path else 0.0


def _aggregate_same_scale_competitor_penalty(candidate: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> float:
    if _candidate_id(candidate) != "candidate_auto_stable" or str(candidate.get("source") or "") != "yolo_zoomed_content":
        return 0.0
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return 0.0
    candidate_area = _bbox_area(bbox)
    if candidate_area <= 0.0 or candidate_area > TARGET_LOCK_AGGREGATE_CANDIDATE_MAX_AREA:
        return 0.0
    candidate_height = float(bbox.get("height", 0.0) or 0.0)
    support_count = _candidate_int_metric(candidate, "support_count")
    support_frame_count = _candidate_int_metric(candidate, "support_frame_count")
    support_confidence = _candidate_float_metric(candidate, "support_confidence")
    motion_anchor_hits = _candidate_int_metric(candidate, "support_motion_anchor_hits")
    if support_count <= 0 or support_frame_count <= 0:
        return 0.0

    for item in candidates:
        if not isinstance(item, dict) or item is candidate or _candidate_id(item) == _candidate_id(candidate):
            continue
        if str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        item_bbox = item.get("bbox")
        if not isinstance(item_bbox, dict):
            continue
        item_area = _bbox_area(item_bbox)
        if item_area <= 0.0:
            continue
        item_height = float(item_bbox.get("height", 0.0) or 0.0)
        area_ratio = item_area / candidate_area
        height_ratio = item_height / max(candidate_height, 1e-9)
        if not (
            TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_AREA_RATIO
            <= area_ratio
            <= TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MAX_AREA_RATIO
            and TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_HEIGHT_RATIO
            <= height_ratio
            <= TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MAX_HEIGHT_RATIO
        ):
            continue
        item_support_count = _candidate_int_metric(item, "support_count")
        item_support_frame_count = _candidate_int_metric(item, "support_frame_count")
        item_support_confidence = _candidate_float_metric(item, "support_confidence")
        item_motion_anchor_hits = _candidate_int_metric(item, "support_motion_anchor_hits")
        if item_support_count < support_count + TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_SUPPORT_ADVANTAGE:
            continue
        if item_support_frame_count < support_frame_count:
            continue
        if item_motion_anchor_hits < max(0, motion_anchor_hits - 1):
            continue
        if item_support_confidence < support_confidence - TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MAX_SUPPORT_CONFIDENCE_GAP:
            continue
        if _candidate_confidence(item) < _candidate_confidence(candidate) + TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_MIN_CONFIDENCE_ADVANTAGE:
            continue
        return TARGET_LOCK_AGGREGATE_SAME_SCALE_COMPETITOR_PENALTY
    return 0.0


def _candidate_rank_score(candidate: dict[str, Any]) -> float:
    confidence, area = _candidate_sort_key(candidate)
    support = 0.0
    try:
        support = float(candidate.get("support_count", 0.0) or 0.0)
    except (TypeError, ValueError):
        support = 0.0
    try:
        support_frame_count = float(candidate.get("support_frame_count", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_frame_count = 0.0
    try:
        support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_confidence = 0.0
    try:
        motion_anchor_hits = float(candidate.get("support_motion_anchor_hits", 0.0) or 0.0)
    except (TypeError, ValueError):
        motion_anchor_hits = 0.0
    support_center_span: float | None
    raw_support_center_span = candidate.get("support_center_span")
    try:
        support_center_span = float(raw_support_center_span) if raw_support_center_span is not None else None
    except (TypeError, ValueError):
        support_center_span = None
    try:
        same_anchor_competitors = float(candidate.get("multiperson_same_anchor_competitor_count", 0.0) or 0.0)
    except (TypeError, ValueError):
        same_anchor_competitors = 0.0
    source = str(candidate.get("source") or "")
    zoom_bonus = 0.20 if source == "yolo_zoomed_content" else 0.0
    stable_bonus = 1.5 if support >= 2 else 0.0
    foreground_penalty = 1.0 if area >= 0.18 and support < 2 else 0.0
    bbox = candidate.get("bbox")
    height = float(bbox.get("height", 0.0) or 0.0) if isinstance(bbox, dict) else 0.0
    aggregate_candidate_bonus = _aggregate_candidate_rank_bonus(
        candidate,
        support_frame_count=support_frame_count,
        support_confidence=support_confidence,
        area=area,
        height=height,
        support_center_span=support_center_span,
    )
    support_confidence_bonus = support_confidence * 0.25 if support >= 2 else 0.0
    unique_support_bonus = min(support_frame_count, 8.0) * 0.03
    motion_anchor_bonus = min(motion_anchor_hits, 3.0) * 0.08
    support_span_penalty = max(0.0, (support_center_span or 0.0) - 0.30) * 0.50
    same_anchor_competitor_penalty = min(same_anchor_competitors, 4.0) * 0.04
    return (
        stable_bonus
        + min(support, 4.0) * 0.25
        + confidence
        + zoom_bonus
        + aggregate_candidate_bonus
        + support_confidence_bonus
        + unique_support_bonus
        + motion_anchor_bonus
        - foreground_penalty
        - support_span_penalty
        - same_anchor_competitor_penalty
        - max(0.0, area - 0.16)
    )


def _stable_small_zoomed_target_competitors(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    candidate_area = _bbox_area(bbox)
    if candidate_area < TARGET_LOCK_ZOOMED_FOREGROUND_DEPRIORITIZE_MIN_AREA:
        return []

    competitors: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict) or item is candidate:
            continue
        if _candidate_id(item) == _candidate_id(candidate):
            continue
        if str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        item_bbox = item.get("bbox")
        if not isinstance(item_bbox, dict):
            continue
        item_area = _bbox_area(item_bbox)
        item_height = float(item_bbox.get("height", 0.0) or 0.0)
        if not (
            TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_AREA
            <= item_area
            <= TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MAX_AREA
            and item_height >= TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_HEIGHT
        ):
            continue
        try:
            support_count = int(item.get("support_count", 0) or 0)
        except (TypeError, ValueError):
            support_count = 0
        try:
            support_frame_count = int(item.get("support_frame_count", 0) or 0)
        except (TypeError, ValueError):
            support_frame_count = 0
        try:
            support_confidence = float(item.get("support_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            support_confidence = 0.0
        try:
            motion_anchor_hits = int(item.get("support_motion_anchor_hits", 0) or 0)
        except (TypeError, ValueError):
            motion_anchor_hits = 0
        if _bbox_center_distance(bbox, item_bbox) < TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_CENTER_DISTANCE:
            continue
        high_confidence_small_target = support_confidence >= TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_SUPPORT_CONFIDENCE
        contextual_small_target = (
            support_count >= TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_SUPPORT
            and support_confidence >= TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_SUPPORT_CONFIDENCE
            and support_frame_count >= TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_SUPPORT_FRAMES
            and item_height >= TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_HEIGHT
            and candidate_area / max(item_area, 1e-9) >= TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_SMALL_TARGET_MIN_AREA_RATIO
            and _has_zoomed_foreground_multiperson_context(candidate, candidates)
        )
        if high_confidence_small_target and (
            support_frame_count < TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_SUPPORT_FRAMES
            or motion_anchor_hits < TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_MOTION_HITS
        ):
            high_confidence_small_target = False
        if not high_confidence_small_target and not contextual_small_target:
            continue
        competitors.append(item)
    return competitors


def _compact_zoomed_target_competitors(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    candidate_area = _bbox_area(bbox)
    candidate_height = float(bbox.get("height", 0.0) or 0.0)
    if (
        candidate_area < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_CONTEXT_MIN_AREA
        or not _has_zoomed_foreground_multiperson_context(candidate, candidates)
        or _candidate_int_metric(candidate, "multiperson_ambiguous_frame_count")
        < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_CONTEXT_MIN_AMBIGUOUS_FRAMES
        or _candidate_int_metric(candidate, "multiperson_competitor_count")
        < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_CONTEXT_MIN_COMPETITORS
    ):
        return []

    competitors: list[dict[str, Any]] = []
    candidate_id = _candidate_id(candidate)
    for item in candidates:
        if not isinstance(item, dict) or item is candidate or _candidate_id(item) == candidate_id:
            continue
        if str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        item_bbox = item.get("bbox")
        if not isinstance(item_bbox, dict):
            continue
        item_area = _bbox_area(item_bbox)
        item_width = float(item_bbox.get("width", 0.0) or 0.0)
        item_height = float(item_bbox.get("height", 0.0) or 0.0)
        if not (
            TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_AREA
            <= item_area
            <= TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MAX_AREA
            and item_height >= TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_HEIGHT
            and item_width <= TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MAX_WIDTH
        ):
            continue
        if (
            candidate_area / max(item_area, 1e-9)
            < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_AREA_RATIO
            and candidate_height / max(item_height, 1e-9)
            < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_HEIGHT_RATIO
        ):
            continue
        if _bbox_center_distance(bbox, item_bbox) < TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_CENTER_DISTANCE:
            continue
        if (
            _candidate_int_metric(item, "support_count")
            < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_SUPPORT
            or _candidate_int_metric(item, "support_frame_count")
            < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_SUPPORT_FRAMES
            or _candidate_float_metric(item, "support_confidence")
            < TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MIN_SUPPORT_CONFIDENCE
        ):
            continue
        support_center_span = _optional_candidate_float_metric(item, "support_center_span")
        if (
            support_center_span is not None
            and support_center_span > TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MAX_CENTER_SPAN
        ):
            continue
        competitors.append(item)
    return competitors


def _has_zoomed_foreground_multiperson_context(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> bool:
    def _int_metric(name: str) -> int:
        try:
            return int(candidate.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    ambiguous_frames = _int_metric("multiperson_ambiguous_frame_count")
    competitors = _int_metric("multiperson_competitor_count")
    if (
        ambiguous_frames >= TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_MIN_AMBIGUOUS_FRAMES
        or competitors >= TARGET_LOCK_ZOOMED_FOREGROUND_CONTEXTUAL_MIN_COMPETITORS
    ):
        return True
    return "target_lock_zoomed_multiperson_manual_review" in _zoomed_multiperson_manual_review_flags(candidate, candidates)


def _zoomed_foreground_context_penalty(candidate: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> float:
    if not _stable_small_zoomed_target_competitors(candidate, candidates) and not _compact_zoomed_target_competitors(
        candidate,
        candidates,
    ):
        return 0.0
    return TARGET_LOCK_ZOOMED_FOREGROUND_DEPRIORITIZE_PENALTY


def _candidate_contextual_rank_score(candidate: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> float:
    return (
        _candidate_rank_score(candidate)
        - _zoomed_foreground_context_penalty(candidate, candidates)
        - _aggregate_same_scale_competitor_penalty(candidate, candidates)
    )


def _mark_deprioritized_zoomed_foreground_candidates(candidates: Sequence[dict[str, Any]]) -> None:
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        competitors = _stable_small_zoomed_target_competitors(candidate, candidates)
        compact_competitors = _compact_zoomed_target_competitors(candidate, candidates)
        competitors = [*competitors, *compact_competitors]
        if not competitors:
            continue
        flags = candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else []
        added_flags = ["target_lock_zoomed_foreground_deprioritized_for_stable_small_target"]
        if compact_competitors:
            added_flags.append("target_lock_zoomed_foreground_deprioritized_for_compact_skater_target")
        if any(
            _candidate_support_confidence(item) < TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_SUPPORT_CONFIDENCE
            for item in competitors
        ):
            added_flags.append("target_lock_zoomed_moderate_foreground_deprioritized_for_stable_small_target")
        candidate["quality_flags"] = _merge_strings(flags, added_flags)


def _stable_zoomed_candidate_auto_lock_flags(candidate: dict[str, Any]) -> list[str]:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return []
    try:
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    try:
        support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
    except (TypeError, ValueError):
        support_frame_count = 0
    try:
        support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_confidence = 0.0
    source = str(candidate.get("source") or "")
    area = _bbox_area(bbox)
    if source != "yolo_zoomed_content" or area <= 0.0:
        return []
    low_aggregate_support = bool(
        support_confidence
        and support_confidence < TARGET_LOCK_TINY_ZOOMED_MIN_SUPPORT_CONFIDENCE
        and area <= TARGET_LOCK_TINY_ZOOMED_MANUAL_REVIEW_MAX_AREA
    )
    if low_aggregate_support:
        return []

    aggregate_stable_target = (
        support_confidence >= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_THRESHOLD
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_UNIQUE_FRAMES
        and area <= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MAX_AREA
    )
    small_stable_target = (
        confidence >= TARGET_LOCK_STABLE_ZOOMED_AUTO_THRESHOLD
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_MIN_SUPPORT
        and area <= TARGET_LOCK_STABLE_ZOOMED_MAX_AREA
    )
    near_threshold_stable_target = (
        confidence >= TARGET_LOCK_STABLE_ZOOMED_NEAR_THRESHOLD
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_NEAR_MIN_SUPPORT
        and area <= TARGET_LOCK_STABLE_ZOOMED_NEAR_MAX_AREA
    )
    if not aggregate_stable_target and not small_stable_target and not near_threshold_stable_target:
        return []
    flags = ["target_lock_stable_zoomed_candidate_auto_locked"]
    if aggregate_stable_target:
        flags.append("target_lock_stable_zoomed_aggregate_confidence_auto_locked")
    if near_threshold_stable_target and not small_stable_target:
        flags.append("target_lock_stable_zoomed_near_threshold_auto_locked")
    return flags


def _remove_quality_flags(candidate: dict[str, Any], flags_to_remove: Sequence[str]) -> None:
    if not flags_to_remove:
        return
    flags = candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else []
    remove_set = set(flags_to_remove)
    candidate["quality_flags"] = [flag for flag in flags if str(flag) not in remove_set]


TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_FLAGS = (
    "target_lock_zoomed_multiperson_background_auto_lock_allowed",
    "target_lock_zoomed_multiperson_foreground_background_auto_lock_allowed",
    "target_lock_zoomed_multiperson_foreground_transient_background_auto_lock_allowed",
    "target_lock_zoomed_multiperson_isolated_background_auto_lock_allowed",
    "target_lock_zoomed_multiperson_clear_compact_target_auto_lock_allowed",
)
TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_OVERRIDDEN_FLAG = (
    "target_lock_zoomed_multiperson_background_auto_lock_allowed_overridden_by_manual_review"
)
TARGET_LOCK_ZOOMED_MULTIPERSON_REVIEW_REASON_FLAGS = (
    "target_lock_zoomed_multiperson_review_same_anchor_competitor",
    "target_lock_zoomed_multiperson_review_selected_pair_competitor",
    "target_lock_zoomed_multiperson_review_near_competitor",
    "target_lock_zoomed_multiperson_review_other_frame_competitors",
    "target_lock_zoomed_multiperson_review_dense_competitors",
    "target_lock_zoomed_multiperson_review_low_motion_anchor_support",
    "target_lock_zoomed_multiperson_review_low_support_confidence",
    "target_lock_zoomed_multiperson_review_low_support_frames",
)
TARGET_LOCK_FOREGROUND_CONTEXT_REVIEW_REASON_FLAGS = (
    "target_lock_foreground_context_review_deprioritized_foreground_competitor",
    "target_lock_foreground_context_review_compact_competitor",
    "target_lock_foreground_context_review_low_support_frames",
    "target_lock_foreground_context_review_low_motion_anchor_support",
    "target_lock_foreground_context_review_selected_pair_competitor",
)


def _clean_background_auto_lock_allowed_conflicts(
    candidates: Sequence[dict[str, Any]],
    *,
    target_lock_status: str | None,
) -> None:
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        flags = candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else []
        if not any(str(flag) in TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_FLAGS for flag in flags):
            continue
        if (
            str(target_lock_status or "") == "auto_locked"
            and not any("_manual_review" in str(flag) for flag in flags)
            and "target_lock_auto_lock_blocked_by_manual_review" not in flags
        ):
            continue
        _remove_quality_flags(candidate, TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_FLAGS)
        cleaned_flags = candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else []
        candidate["quality_flags"] = _merge_strings(
            cleaned_flags,
            [TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_OVERRIDDEN_FLAG],
        )


def _auto_lock_blocked_flags(
    *,
    stable_zoomed_auto_lock: bool,
    distant_single_jump_auto_lock: bool,
) -> list[str]:
    flags: list[str] = []
    if stable_zoomed_auto_lock:
        flags.append("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review")
    if distant_single_jump_auto_lock:
        flags.append("target_lock_distant_single_jump_auto_lock_blocked_by_manual_review")
    if flags:
        flags.append("target_lock_auto_lock_blocked_by_manual_review")
    return flags


def _zoomed_multiperson_review_reason_flags(candidate: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") > 0:
        flags.append("target_lock_zoomed_multiperson_review_same_anchor_competitor")
    if _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") > 0:
        flags.append("target_lock_zoomed_multiperson_review_selected_pair_competitor")
    nearest_distance = _optional_candidate_float_metric(candidate, "multiperson_nearest_center_distance")
    if nearest_distance is not None and nearest_distance < TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_CENTER_DISTANCE:
        flags.append("target_lock_zoomed_multiperson_review_near_competitor")
    if _candidate_int_metric(candidate, "multiperson_other_frame_ambiguous_count") > 0:
        flags.append("target_lock_zoomed_multiperson_review_other_frame_competitors")
    if _candidate_int_metric(candidate, "multiperson_competitor_count") >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_COMPETITORS:
        flags.append("target_lock_zoomed_multiperson_review_dense_competitors")
    if _candidate_int_metric(candidate, "support_motion_anchor_hits") < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_MOTION_HITS:
        flags.append("target_lock_zoomed_multiperson_review_low_motion_anchor_support")
    if _candidate_float_metric(candidate, "support_confidence") < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT_CONFIDENCE:
        flags.append("target_lock_zoomed_multiperson_review_low_support_confidence")
    if _candidate_int_metric(candidate, "support_frame_count") < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT_FRAMES:
        flags.append("target_lock_zoomed_multiperson_review_low_support_frames")
    return flags


def _tiny_zoomed_candidate_requires_manual_review(candidate: dict[str, Any]) -> bool:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    if _bbox_area(bbox) > TARGET_LOCK_TINY_ZOOMED_MANUAL_REVIEW_MAX_AREA:
        return False
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    try:
        support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
    except (TypeError, ValueError):
        support_frame_count = 0
    try:
        support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_confidence = 0.0
    if support_count < 2 and support_frame_count < 2:
        return True
    return bool(support_confidence and support_confidence < TARGET_LOCK_TINY_ZOOMED_MIN_SUPPORT_CONFIDENCE)


def _distant_single_jump_auto_lock_flags(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    analysis_profile: str | None,
) -> list[str]:
    if str(analysis_profile or "").strip().lower() != "jump":
        return []
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    area = _bbox_area(bbox)
    if area <= 0.0 or area > TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_AREA:
        return []
    try:
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    try:
        support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
    except (TypeError, ValueError):
        support_frame_count = 0
    try:
        support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_confidence = 0.0
    if (
        confidence < TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_CONFIDENCE
        or support_count < TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_SUPPORT
        or support_frame_count < TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_UNIQUE_FRAMES
        or support_confidence < TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_SUPPORT_CONFIDENCE
    ):
        return []

    competitors: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict) or item is candidate or _candidate_id(item) == _candidate_id(candidate):
            continue
        if str(item.get("source") or "") == "layout_fallback":
            continue
        if _candidate_matches_anchor(item, candidate):
            continue
        try:
            item_confidence = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            item_confidence = 0.0
        if item_confidence >= TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_COMPETITOR_CONFIDENCE:
            competitors.append(item)
    if competitors:
        return []
    return [
        "target_lock_distant_single_jump_auto_locked",
    ]


def _zoomed_multiperson_manual_review_flags(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    same_anchor_only: bool = False,
) -> list[str]:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    candidate_anchor_frame = _candidate_anchor_key(candidate)

    by_anchor_frame: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        if not isinstance(item, dict) or str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        if _candidate_confidence(item) < TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CONFIDENCE:
            continue
        if not isinstance(item.get("bbox"), dict):
            continue
        anchor_frame = _candidate_anchor_key(item)
        if not anchor_frame:
            continue
        if same_anchor_only and anchor_frame != candidate_anchor_frame:
            continue
        by_anchor_frame.setdefault(anchor_frame, []).append(item)

    ignored_fragment = False
    ignored_duplicate = False
    for frame_candidates in by_anchor_frame.values():
        for index, first in enumerate(frame_candidates):
            first_bbox = first.get("bbox")
            if not isinstance(first_bbox, dict):
                continue
            for second in frame_candidates[index + 1 :]:
                second_bbox = second.get("bbox")
                if not isinstance(second_bbox, dict):
                    continue
                if _bbox_center_distance(first_bbox, second_bbox) >= TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CENTER_DISTANCE:
                    if _zoomed_multiperson_pair_is_duplicate_body_box(first, second):
                        ignored_duplicate = True
                        continue
                    if _zoomed_multiperson_pair_is_weak_fragment(candidate, first, second):
                        ignored_fragment = True
                        continue
                    return ["target_lock_zoomed_multiperson_manual_review"]
    if ignored_duplicate:
        return ["target_lock_zoomed_multiperson_duplicate_body_box_ignored"]
    return ["target_lock_zoomed_multiperson_fragment_ignored"] if ignored_fragment else []


def _zoomed_multiperson_scale_competitor_manual_review_flags(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> list[str]:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return []
    if _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") > 0:
        return []
    if _candidate_int_metric(candidate, "multiperson_other_frame_ambiguous_count") <= 0:
        return []

    selected_area = _bbox_area(bbox)
    selected_height = float(bbox.get("height", 0.0) or 0.0)
    if (
        selected_area < TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SELECTED_AREA
        or selected_height < TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SELECTED_HEIGHT
    ):
        return []

    support_count = _candidate_int_metric(candidate, "support_count")
    support_frame_count = _candidate_int_metric(candidate, "support_frame_count")
    support_confidence = _candidate_float_metric(candidate, "support_confidence")
    motion_anchor_hits = _candidate_int_metric(candidate, "support_motion_anchor_hits")
    if (
        support_count < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT
        or support_frame_count < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT_FRAMES
        or support_confidence < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_RELAXED_MIN_CONFIDENCE
        or motion_anchor_hits < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_MOTION_HITS
    ):
        return []

    selected_id = _candidate_id(candidate)
    for item in candidates:
        if not isinstance(item, dict) or item is candidate:
            continue
        if _candidate_id(item) == selected_id:
            continue
        if str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        item_bbox = item.get("bbox")
        if not isinstance(item_bbox, dict):
            continue
        item_area = _bbox_area(item_bbox)
        item_height = float(item_bbox.get("height", 0.0) or 0.0)
        if (
            item_area < TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_AREA
            or item_height < TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_HEIGHT
            or item_area > selected_area * TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_AREA_RATIO
            or item_height > selected_height * TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_HEIGHT_RATIO
        ):
            continue

        item_support_count = _candidate_int_metric(item, "support_count")
        item_support_frame_count = _candidate_int_metric(item, "support_frame_count")
        item_support_confidence = _candidate_float_metric(item, "support_confidence")
        item_motion_anchor_hits = _candidate_int_metric(item, "support_motion_anchor_hits")
        if item_support_count < max(
            TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SUPPORT,
            int(support_count * TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SUPPORT_RATIO),
        ):
            continue
        if item_support_frame_count < max(
            TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SUPPORT,
            support_frame_count - TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_SUPPORT_FRAME_GAP,
        ):
            continue
        if item_support_confidence < max(
            TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MIN_SUPPORT_CONFIDENCE,
            support_confidence - TARGET_LOCK_ZOOMED_MULTIPERSON_SCALE_COMPETITOR_MAX_SUPPORT_CONFIDENCE_GAP,
        ):
            continue
        if item_motion_anchor_hits < motion_anchor_hits:
            continue
        return ["target_lock_zoomed_multiperson_scale_competitor_manual_review"]
    return []


def _stable_zoomed_multiperson_background_auto_lock_allowed(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False

    def _int_metric(name: str) -> int:
        try:
            return int(candidate.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _float_metric(name: str) -> float:
        try:
            return float(candidate.get(name, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _optional_float_metric(name: str) -> float | None:
        try:
            value = candidate.get(name)
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    support_count = _int_metric("support_count")
    support_frame_count = _int_metric("support_frame_count")
    support_confidence = _float_metric("support_confidence")
    support_center_span = _optional_float_metric("support_center_span")
    if support_center_span is None:
        return False
    area = _bbox_area(bbox)
    selected_pair_frames = _int_metric("multiperson_selected_pair_frame_count")
    same_anchor_competitors = _int_metric("multiperson_same_anchor_competitor_count")
    competitor_count = _int_metric("multiperson_competitor_count")
    motion_anchor_hits = _int_metric("support_motion_anchor_hits")
    other_frame_ambiguous_count = _int_metric("multiperson_other_frame_ambiguous_count")
    height = float(bbox.get("height", 0.0) or 0.0)
    if selected_pair_frames > 0 or same_anchor_competitors > 0:
        return False
    if _stable_zoomed_multiperson_background_tiny_dense_risk(
        candidate,
        area=area,
        height=height,
        support_center_span=support_center_span,
        support_confidence=support_confidence,
        other_frame_ambiguous_count=other_frame_ambiguous_count,
    ):
        return False
    if _stable_zoomed_multiperson_background_dispersed_small_risk(
        candidate,
        area=area,
        support_center_span=support_center_span,
        support_confidence=support_confidence,
        other_frame_ambiguous_count=other_frame_ambiguous_count,
    ):
        return False
    small_moving_background_risk = (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MAX_AREA
        and support_center_span >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_CENTER_SPAN
        and other_frame_ambiguous_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_OTHER_FRAMES
        and (
            motion_anchor_hits < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_MOTION_HITS
            or support_confidence
            < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_SUPPORT_CONFIDENCE
            or _int_metric("multiperson_competitor_count")
            >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_COMPETITORS
        )
    )
    if small_moving_background_risk:
        return _stable_zoomed_multiperson_high_support_small_auto_lock_allowed(
            candidate,
            area=area,
            support_count=support_count,
            support_frame_count=support_frame_count,
            support_confidence=support_confidence,
            support_center_span=support_center_span,
            motion_anchor_hits=motion_anchor_hits,
            selected_pair_frames=selected_pair_frames,
            other_frame_ambiguous_count=other_frame_ambiguous_count,
        )

    if _stable_zoomed_multiperson_background_dense_moving_risk(
        support_center_span=support_center_span,
        other_frame_ambiguous_count=other_frame_ambiguous_count,
        competitor_count=competitor_count,
    ):
        return False

    narrow_background_lock = (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_SUPPORT_CONFIDENCE
        and motion_anchor_hits >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_MOTION_HITS
        and selected_pair_frames <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_SELECTED_PAIR_FRAMES
        and same_anchor_competitors <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_SAME_ANCHOR_COMPETITORS
    )
    if narrow_background_lock:
        return True

    large_moving_background_risk = (
        area >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_AREA
        and support_center_span >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_CENTER_SPAN
        and other_frame_ambiguous_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_OTHER_FRAMES
        and _int_metric("multiperson_competitor_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_COMPETITORS
    )
    if large_moving_background_risk:
        return False
    compact_transient_background_lock = (
        TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_AREA
        <= area
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_AREA
        and _candidate_confidence(candidate)
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_CONFIDENCE
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_SUPPORT_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_CENTER_SPAN
        and motion_anchor_hits >= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MIN_MOTION_HITS
        and selected_pair_frames == 0
        and _int_metric("multiperson_same_anchor_competitor_count") == 0
        and other_frame_ambiguous_count <= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_OTHER_FRAMES
        and _int_metric("multiperson_competitor_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_COMPACT_TRANSIENT_AUTO_MAX_COMPETITORS
    )
    if compact_transient_background_lock:
        return True
    medium_transient_background_lock = (
        TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_AREA
        <= area
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_SUPPORT_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_CENTER_SPAN
        and motion_anchor_hits >= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MIN_MOTION_HITS
        and selected_pair_frames == 0
        and _int_metric("multiperson_same_anchor_competitor_count") == 0
        and other_frame_ambiguous_count <= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_OTHER_FRAMES
        and _int_metric("multiperson_competitor_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_MEDIUM_TRANSIENT_AUTO_MAX_COMPETITORS
    )
    if medium_transient_background_lock:
        return True
    sparse_background_lock = (
        TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_AREA
        <= area
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_AREA
        and _candidate_confidence(candidate)
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_CONFIDENCE
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_SUPPORT_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_CENTER_SPAN
        and motion_anchor_hits >= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_MOTION_HITS
        and selected_pair_frames == 0
        and _int_metric("multiperson_same_anchor_competitor_count") == 0
        and other_frame_ambiguous_count <= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_OTHER_FRAMES
        and _int_metric("multiperson_competitor_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MAX_COMPETITORS
        and (
            _optional_float_metric("multiperson_nearest_center_distance") or 0.0
        )
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_SPARSE_BACKGROUND_AUTO_MIN_CENTER_DISTANCE
    )
    if sparse_background_lock:
        return True
    small_background_only_lock = (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_SUPPORT_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MAX_CENTER_SPAN
        and motion_anchor_hits >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_MOTION_HITS
        and _int_metric("multiperson_same_anchor_competitor_count") == 0
        and other_frame_ambiguous_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_OTHER_FRAMES
    )
    small_moderate_background_only_lock = (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MODERATE_AUTO_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MODERATE_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MODERATE_AUTO_MIN_SUPPORT_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MAX_CENTER_SPAN
        and motion_anchor_hits >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_MOTION_HITS
        and same_anchor_competitors == 0
        and other_frame_ambiguous_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_AUTO_MIN_OTHER_FRAMES
    )
    strong_background_only_lock = (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_RELAXED_MIN_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MAX_CENTER_SPAN
    )
    dense_background_only_lock = (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_DENSE_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_DENSE_MIN_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_DENSE_MAX_CENTER_SPAN
    )
    wide_moving_background_only_lock = (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MIN_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_ONLY_AUTO_WIDE_MAX_CENTER_SPAN
        and same_anchor_competitors == 0
    )
    return (
        selected_pair_frames == 0
        and (
            small_background_only_lock
            or small_moderate_background_only_lock
            or (
                motion_anchor_hits >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_AUTO_MIN_MOTION_HITS
                and (
                    strong_background_only_lock
                    or dense_background_only_lock
                    or wide_moving_background_only_lock
                )
            )
        )
    )


def _stable_zoomed_multiperson_high_support_small_auto_lock_allowed(
    candidate: dict[str, Any],
    *,
    area: float,
    support_count: int,
    support_frame_count: int,
    support_confidence: float,
    support_center_span: float,
    motion_anchor_hits: int,
    selected_pair_frames: int,
    other_frame_ambiguous_count: int,
) -> bool:
    return (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MAX_AREA
        and support_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_SUPPORT
        and support_frame_count
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_SUPPORT_FRAMES
        and support_confidence
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_SUPPORT_CONFIDENCE
        and support_center_span <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MAX_CENTER_SPAN
        and motion_anchor_hits
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MIN_MOTION_HITS
        and selected_pair_frames == 0
        and _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") == 0
        and other_frame_ambiguous_count
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MAX_OTHER_FRAMES
        and _candidate_int_metric(candidate, "multiperson_competitor_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_HIGH_SUPPORT_SMALL_AUTO_MAX_COMPETITORS
    )


def _stable_zoomed_multiperson_background_dense_moving_risk(
    *,
    support_center_span: float | None,
    other_frame_ambiguous_count: int,
    competitor_count: int,
) -> bool:
    if support_center_span is None:
        return False
    return (
        support_center_span >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DENSE_MOVING_RISK_MIN_CENTER_SPAN
        and other_frame_ambiguous_count
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DENSE_MOVING_RISK_MIN_OTHER_FRAMES
        and competitor_count
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DENSE_MOVING_RISK_MIN_COMPETITORS
    )


def _zoomed_background_competitors(candidate: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    candidate_id = _candidate_id(candidate)
    competitors: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict) or item is candidate:
            continue
        if _candidate_id(item) == candidate_id:
            continue
        if str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        if _candidate_confidence(item) < TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CONFIDENCE:
            continue
        if not isinstance(item.get("bbox"), dict):
            continue
        if _candidate_matches_anchor(item, candidate):
            continue
        competitors.append(item)
    return competitors


def _stable_zoomed_foreground_with_tiny_background_auto_lock_allowed(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False

    area = _bbox_area(bbox)
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    if (
        area < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_AREA
        or width < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_WIDTH
        or height < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_HEIGHT
        or _candidate_confidence(candidate) < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_CONFIDENCE
        or _candidate_int_metric(candidate, "support_count") < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_SUPPORT
        or _candidate_int_metric(candidate, "support_frame_count") < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_SUPPORT_FRAMES
        or _candidate_float_metric(candidate, "support_confidence")
        < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_SUPPORT_CONFIDENCE
        or _candidate_int_metric(candidate, "support_motion_anchor_hits")
        < TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_MOTION_HITS
        or _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") != 0
        or _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") != 0
    ):
        return False

    competitors = _zoomed_background_competitors(candidate, candidates)
    if not competitors:
        return False

    max_competitor_area = max(_bbox_area(item["bbox"]) for item in competitors)
    max_competitor_height = max(float(item["bbox"].get("height", 0.0) or 0.0) for item in competitors)
    if max_competitor_area <= 0.0 or max_competitor_height <= 0.0:
        return False
    return (
        area / max_competitor_area >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_AREA_RATIO
        and height / max_competitor_height >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_AUTO_MIN_HEIGHT_RATIO
    )


def _stable_zoomed_foreground_with_transient_background_auto_lock_allowed(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    area = _bbox_area(bbox)
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    return (
        area >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_AREA
        and width >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_WIDTH
        and height >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_HEIGHT
        and _candidate_confidence(candidate)
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_CONFIDENCE
        and _candidate_int_metric(candidate, "support_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_SUPPORT
        and _candidate_int_metric(candidate, "support_frame_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_SUPPORT_FRAMES
        and _candidate_float_metric(candidate, "support_confidence")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_SUPPORT_CONFIDENCE
        and _candidate_int_metric(candidate, "support_motion_anchor_hits")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MIN_MOTION_HITS
        and _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") == 0
        and _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") == 0
        and _candidate_int_metric(candidate, "multiperson_other_frame_ambiguous_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MAX_OTHER_FRAMES
        and _candidate_int_metric(candidate, "multiperson_competitor_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_FOREGROUND_TRANSIENT_AUTO_MAX_COMPETITORS
    )


def _stable_zoomed_multiperson_isolated_auto_lock_allowed(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    nearest_center_distance = _optional_candidate_float_metric(candidate, "multiperson_nearest_center_distance")
    if nearest_center_distance is None:
        return False
    area = _bbox_area(bbox)
    return (
        TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_AREA
        <= area
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_AREA
        and _candidate_confidence(candidate)
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_CONFIDENCE
        and _candidate_int_metric(candidate, "support_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SUPPORT
        and _candidate_int_metric(candidate, "support_frame_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SUPPORT_FRAMES
        and _candidate_float_metric(candidate, "support_confidence")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SUPPORT_CONFIDENCE
        and _candidate_int_metric(candidate, "support_motion_anchor_hits")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_MOTION_HITS
        and _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_SAME_ANCHOR_COMPETITORS
        and _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") == 0
        and _candidate_int_metric(candidate, "multiperson_other_frame_ambiguous_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_OTHER_FRAMES
        and _candidate_int_metric(candidate, "multiperson_competitor_count")
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MAX_COMPETITORS
        and nearest_center_distance >= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_CENTER_DISTANCE
    )


def _stable_zoomed_multiperson_clear_compact_auto_lock_allowed(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    area = _bbox_area(bbox)
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    return (
        TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_AREA
        <= area
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_AREA
        and TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_WIDTH
        <= width
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_WIDTH
        and TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_HEIGHT
        <= height
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_HEIGHT
        and _candidate_confidence(candidate)
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_CONFIDENCE
        and _candidate_int_metric(candidate, "support_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_SUPPORT
        and _candidate_int_metric(candidate, "support_frame_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_SUPPORT_FRAMES
        and _candidate_float_metric(candidate, "support_confidence")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_SUPPORT_CONFIDENCE
        and (
            _optional_candidate_float_metric(candidate, "support_center_span") or 1.0
        )
        <= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MAX_CENTER_SPAN
        and _candidate_int_metric(candidate, "support_motion_anchor_hits")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_MOTION_HITS
        and _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") == 0
        and _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") == 0
        and _candidate_int_metric(candidate, "multiperson_other_frame_ambiguous_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_OTHER_FRAMES
        and _candidate_int_metric(candidate, "multiperson_competitor_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_CLEAR_COMPACT_AUTO_MIN_COMPETITORS
    )


def _zoomed_multiperson_selected_pair_min_distance(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> float | None:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return None
    candidate_bbox = candidate.get("bbox")
    if not isinstance(candidate_bbox, dict):
        return None
    candidate_anchor_frame = _candidate_anchor_key(candidate)
    if not candidate_anchor_frame:
        return None
    selected_id = _candidate_id(candidate)
    distances: list[float] = []
    for item in candidates:
        if not isinstance(item, dict) or item is candidate:
            continue
        if _candidate_id(item) == selected_id:
            continue
        if str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        if _candidate_confidence(item) < TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CONFIDENCE:
            continue
        if _candidate_anchor_key(item) != candidate_anchor_frame:
            continue
        item_bbox = item.get("bbox")
        if not isinstance(item_bbox, dict):
            continue
        if _zoomed_multiperson_pair_is_duplicate_body_box(candidate, item):
            continue
        if _zoomed_multiperson_pair_is_weak_fragment(candidate, candidate, item):
            continue
        distances.append(_bbox_center_distance(candidate_bbox, item_bbox))
    return min(distances) if distances else None


def _stable_zoomed_multiperson_background_tiny_dense_risk(
    candidate: dict[str, Any],
    *,
    area: float,
    height: float,
    support_center_span: float | None,
    support_confidence: float,
    other_frame_ambiguous_count: int,
) -> bool:
    if support_center_span is None:
        return False
    return (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MAX_AREA
        and height <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MAX_HEIGHT
        and support_center_span >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MIN_CENTER_SPAN
        and other_frame_ambiguous_count
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MIN_OTHER_FRAMES
        and _candidate_int_metric(candidate, "multiperson_competitor_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MIN_COMPETITORS
        and support_confidence < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_TINY_DENSE_RISK_MAX_SUPPORT_CONFIDENCE
    )


def _stable_zoomed_multiperson_background_dispersed_small_risk(
    candidate: dict[str, Any],
    *,
    area: float,
    support_center_span: float | None,
    support_confidence: float,
    other_frame_ambiguous_count: int,
) -> bool:
    if support_center_span is None:
        return False
    return (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MAX_AREA
        and support_center_span >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MIN_CENTER_SPAN
        and other_frame_ambiguous_count
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MIN_OTHER_FRAMES
        and _candidate_int_metric(candidate, "multiperson_competitor_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MIN_COMPETITORS
        and support_confidence < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_DISPERSED_SMALL_RISK_MAX_SUPPORT_CONFIDENCE
    )


def _stable_zoomed_multiperson_background_auto_lock_blocked_flags(candidate: dict[str, Any]) -> list[str]:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return []
    support_center_span = _optional_candidate_float_metric(candidate, "support_center_span")
    if support_center_span is None:
        return []
    area = _bbox_area(bbox)
    height = float(bbox.get("height", 0.0) or 0.0)
    support_confidence = _candidate_float_metric(candidate, "support_confidence")
    motion_anchor_hits = _candidate_int_metric(candidate, "support_motion_anchor_hits")
    other_frame_ambiguous_count = _candidate_int_metric(candidate, "multiperson_other_frame_ambiguous_count")
    if _stable_zoomed_multiperson_background_tiny_dense_risk(
        candidate,
        area=area,
        height=height,
        support_center_span=support_center_span,
        support_confidence=support_confidence,
        other_frame_ambiguous_count=other_frame_ambiguous_count,
    ):
        return ["target_lock_zoomed_multiperson_background_auto_lock_blocked_tiny_dense_risk"]
    if _stable_zoomed_multiperson_background_dispersed_small_risk(
        candidate,
        area=area,
        support_center_span=support_center_span,
        support_confidence=support_confidence,
        other_frame_ambiguous_count=other_frame_ambiguous_count,
    ):
        return ["target_lock_zoomed_multiperson_background_auto_lock_blocked_dispersed_small_risk"]
    if (
        area <= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MAX_AREA
        and support_center_span >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_CENTER_SPAN
        and other_frame_ambiguous_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_OTHER_FRAMES
        and (
            motion_anchor_hits < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_MOTION_HITS
            or support_confidence
            < TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_SUPPORT_CONFIDENCE
            or _candidate_int_metric(candidate, "multiperson_competitor_count")
            >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_SMALL_MOVING_RISK_MIN_COMPETITORS
        )
    ):
        if _stable_zoomed_multiperson_high_support_small_auto_lock_allowed(
            candidate,
            area=area,
            support_count=_candidate_int_metric(candidate, "support_count"),
            support_frame_count=_candidate_int_metric(candidate, "support_frame_count"),
            support_confidence=support_confidence,
            support_center_span=support_center_span,
            motion_anchor_hits=motion_anchor_hits,
            selected_pair_frames=_candidate_int_metric(candidate, "multiperson_selected_pair_frame_count"),
            other_frame_ambiguous_count=other_frame_ambiguous_count,
        ):
            return []
        return ["target_lock_zoomed_multiperson_background_auto_lock_blocked_small_moving_risk"]
    if (
        area >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_AREA
        and support_center_span >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_CENTER_SPAN
        and other_frame_ambiguous_count >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_OTHER_FRAMES
        and _candidate_int_metric(candidate, "multiperson_competitor_count")
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_BACKGROUND_LARGE_RISK_MIN_COMPETITORS
    ):
        return ["target_lock_zoomed_multiperson_background_auto_lock_blocked_large_moving_risk"]
    if _stable_zoomed_multiperson_background_dense_moving_risk(
        support_center_span=support_center_span,
        other_frame_ambiguous_count=other_frame_ambiguous_count,
        competitor_count=_candidate_int_metric(candidate, "multiperson_competitor_count"),
    ):
        return ["target_lock_zoomed_multiperson_background_auto_lock_blocked_dense_moving_risk"]
    if (
        _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") > 0
        or _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") > 0
    ):
        return ["target_lock_zoomed_multiperson_background_auto_lock_blocked_direct_competitor_risk"]
    return []


def _zoomed_multiperson_pair_is_weak_fragment(
    selected: dict[str, Any],
    first: dict[str, Any],
    second: dict[str, Any],
) -> bool:
    selected_bbox = selected.get("bbox")
    if not isinstance(selected_bbox, dict):
        return False
    selected_area = _bbox_area(selected_bbox)
    if selected_area <= 0.0:
        return False
    try:
        support_frame_count = int(selected.get("support_frame_count", 0) or 0)
    except (TypeError, ValueError):
        support_frame_count = 0
    try:
        support_confidence = float(selected.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_confidence = 0.0
    if (
        support_frame_count < TARGET_LOCK_ZOOMED_FRAGMENT_MIN_TOP_SUPPORT_FRAMES
        or support_confidence < TARGET_LOCK_ZOOMED_FRAGMENT_MIN_TOP_SUPPORT_CONFIDENCE
    ):
        return False

    selected_id = _candidate_id(selected)
    if selected_id not in {_candidate_id(first), _candidate_id(second)}:
        return False

    track_candidate = first if _candidate_id(first) == selected_id else second
    competitor = second if _candidate_id(first) == selected_id else first
    competitor_bbox = competitor.get("bbox")
    if not isinstance(competitor_bbox, dict):
        return False
    track_bbox = track_candidate.get("bbox")
    track_area = _bbox_area(track_bbox) if isinstance(track_bbox, dict) else 0.0
    competitor_area = _bbox_area(competitor_bbox)
    if competitor_area <= 0.0 or competitor_area > TARGET_LOCK_ZOOMED_FRAGMENT_MAX_AREA:
        return False
    reference_area = max(selected_area, track_area)
    if reference_area <= 0.0 or competitor_area / reference_area > TARGET_LOCK_ZOOMED_FRAGMENT_MAX_AREA_RATIO:
        return False
    track_confidence = max(_candidate_confidence(selected), _candidate_confidence(track_candidate))
    return track_confidence >= _candidate_confidence(competitor) + TARGET_LOCK_ZOOMED_FRAGMENT_MIN_CONFIDENCE_ADVANTAGE


def _zoomed_multiperson_pair_is_duplicate_body_box(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_bbox = first.get("bbox")
    second_bbox = second.get("bbox")
    if not isinstance(first_bbox, dict) or not isinstance(second_bbox, dict):
        return False
    first_area = _bbox_area(first_bbox)
    second_area = _bbox_area(second_bbox)
    if first_area <= 0.0 or second_area <= 0.0:
        return False
    area_ratio = max(first_area, second_area) / max(min(first_area, second_area), 1e-9)
    if area_ratio > TARGET_LOCK_ZOOMED_MULTIPERSON_DUPLICATE_MAX_AREA_RATIO:
        return False
    return (
        _bbox_iou(first_bbox, second_bbox) >= TARGET_LOCK_ZOOMED_MULTIPERSON_DUPLICATE_MIN_IOU
        or _bbox_min_containment(first_bbox, second_bbox)
        >= TARGET_LOCK_ZOOMED_MULTIPERSON_DUPLICATE_MIN_CONTAINMENT
    )


def _zoomed_multiperson_diagnostics(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return {
            "multiperson_ambiguous_frame_count": 0,
            "multiperson_competitor_count": 0,
            "multiperson_same_anchor_competitor_count": 0,
            "multiperson_selected_pair_frame_count": 0,
            "multiperson_selected_pair_competitor_count": 0,
            "multiperson_other_frame_ambiguous_count": 0,
            "multiperson_nearest_center_distance": None,
            "multiperson_max_competitor_confidence": None,
            "multiperson_ignored_fragment_count": 0,
            "multiperson_ignored_duplicate_body_box_count": 0,
        }

    selected_id = _candidate_id(candidate)
    candidate_anchor_frame = _candidate_anchor_key(candidate)
    by_anchor_frame: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        if not isinstance(item, dict) or str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        if _candidate_confidence(item) < TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CONFIDENCE:
            continue
        if not isinstance(item.get("bbox"), dict):
            continue
        anchor_frame = _candidate_anchor_key(item)
        if not anchor_frame:
            continue
        by_anchor_frame.setdefault(anchor_frame, []).append(item)

    ambiguous_frames: set[str] = set()
    competitor_ids: set[str] = set()
    same_anchor_competitor_ids: set[str] = set()
    selected_pair_frames: set[str] = set()
    selected_pair_competitor_ids: set[str] = set()
    center_distances: list[float] = []
    competitor_confidences: list[float] = []
    ignored_fragment_count = 0
    ignored_duplicate_count = 0

    for anchor_frame, frame_candidates in by_anchor_frame.items():
        for index, first in enumerate(frame_candidates):
            first_bbox = first.get("bbox")
            if not isinstance(first_bbox, dict):
                continue
            for second in frame_candidates[index + 1 :]:
                second_bbox = second.get("bbox")
                if not isinstance(second_bbox, dict):
                    continue
                center_distance = _bbox_center_distance(first_bbox, second_bbox)
                if center_distance < TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CENTER_DISTANCE:
                    continue
                if _zoomed_multiperson_pair_is_duplicate_body_box(first, second):
                    ignored_duplicate_count += 1
                    continue
                if _zoomed_multiperson_pair_is_weak_fragment(candidate, first, second):
                    ignored_fragment_count += 1
                    continue
                ambiguous_frames.add(anchor_frame)
                center_distances.append(center_distance)

                first_id = _candidate_id(first)
                second_id = _candidate_id(second)
                selected_in_pair = selected_id in {first_id, second_id}
                pair_competitors = [item for item in (first, second) if _candidate_id(item) != selected_id]
                for competitor in pair_competitors:
                    competitor_id = _candidate_id(competitor)
                    if not competitor_id:
                        continue
                    competitor_ids.add(competitor_id)
                    competitor_confidences.append(_candidate_confidence(competitor))
                    if anchor_frame == candidate_anchor_frame:
                        same_anchor_competitor_ids.add(competitor_id)
                    if selected_in_pair:
                        selected_pair_frames.add(anchor_frame)
                        selected_pair_competitor_ids.add(competitor_id)
                if not selected_in_pair:
                    competitor_confidences.extend([_candidate_confidence(first), _candidate_confidence(second)])

    return {
        "multiperson_ambiguous_frame_count": len(ambiguous_frames),
        "multiperson_competitor_count": len(competitor_ids),
        "multiperson_same_anchor_competitor_count": len(same_anchor_competitor_ids),
        "multiperson_selected_pair_frame_count": len(selected_pair_frames),
        "multiperson_selected_pair_competitor_count": len(selected_pair_competitor_ids),
        "multiperson_other_frame_ambiguous_count": max(0, len(ambiguous_frames) - len(selected_pair_frames)),
        "multiperson_nearest_center_distance": (
            round(min(center_distances), 4)
            if center_distances
            else None
        ),
        "multiperson_max_competitor_confidence": (
            round(max(competitor_confidences), 4)
            if competitor_confidences
            else None
        ),
        "multiperson_ignored_fragment_count": ignored_fragment_count,
        "multiperson_ignored_duplicate_body_box_count": ignored_duplicate_count,
    }


def _candidate_anchor_key(candidate: dict[str, Any]) -> str:
    anchor_frame = str(candidate.get("anchor_frame") or "").strip()
    if anchor_frame:
        return anchor_frame
    candidate_id = _candidate_id(candidate)
    parts = candidate_id.split("_")
    if len(parts) >= 2 and parts[0] == "anchor" and parts[1].isdigit():
        return f"anchor_{parts[1]}"
    return ""


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_support_confidence(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_effective_lock_confidence(candidate: dict[str, Any], fallback: float = 0.0) -> float:
    values = [_candidate_confidence(candidate), fallback]
    try:
        values.append(float(candidate.get("support_confidence", 0.0) or 0.0))
    except (TypeError, ValueError):
        pass
    return max(values)


def _is_tiny_stable_candidate(candidate: dict[str, Any]) -> bool:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    return (
        str(candidate.get("source") or "") == "yolo_zoomed_content"
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_MIN_SUPPORT
        and _bbox_area(bbox) <= TARGET_LOCK_TINY_STABLE_MAX_AREA
    )


def _is_complete_body_candidate(candidate: dict[str, Any]) -> bool:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    area = _bbox_area(bbox)
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    source = str(candidate.get("source") or "")
    return (
        source in {"yolo_preview", "detector", "yolo_preview_multi_anchor"}
        and _candidate_confidence(candidate) >= TARGET_LOCK_AUTO_THRESHOLD
        and TARGET_LOCK_COMPLETE_BODY_MIN_AREA <= area <= TARGET_LOCK_COMPLETE_BODY_MAX_AREA
        and width >= TARGET_LOCK_COMPLETE_BODY_MIN_WIDTH
        and height >= TARGET_LOCK_COMPLETE_BODY_MIN_HEIGHT
    )


def _tiny_target_supported_by_deprioritized_zoomed_foreground_context(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> bool:
    top_bbox = top_candidate.get("bbox")
    if not isinstance(top_bbox, dict):
        return False
    top_id = _candidate_id(top_candidate)
    for item in candidates:
        if not isinstance(item, dict) or _candidate_id(item) == top_id:
            continue
        flags = item.get("quality_flags") if isinstance(item.get("quality_flags"), list) else []
        if "target_lock_zoomed_moderate_foreground_deprioritized_for_stable_small_target" not in flags:
            continue
        if any(_candidate_id(competitor) == top_id for competitor in _stable_small_zoomed_target_competitors(item, candidates)):
            return True
    return False


def _foreground_contextual_small_target_manual_review_required(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> bool:
    return bool(_foreground_contextual_small_target_review_reason_flags(top_candidate, candidates))


def _foreground_contextual_small_target_review_reason_flags(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> list[str]:
    foreground_context = _tiny_target_supported_by_deprioritized_zoomed_foreground_context(
        top_candidate,
        candidates,
    )
    compact_context = any(
        _candidate_id(top_candidate) == _candidate_id(item)
        for candidate in candidates
        if isinstance(candidate, dict)
        for item in _compact_zoomed_target_competitors(candidate, candidates)
    )
    if not foreground_context and not compact_context:
        return []
    bbox = top_candidate.get("bbox")
    if not isinstance(bbox, dict):
        return []
    max_area = (
        TARGET_LOCK_ZOOMED_FOREGROUND_COMPACT_TARGET_MAX_AREA
        if compact_context
        else TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MAX_AREA
    )
    if _bbox_area(bbox) > max_area:
        return []

    trigger_flags: list[str] = []
    if (
        _candidate_int_metric(top_candidate, "support_frame_count")
        < TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_SUPPORT_FRAMES
    ):
        trigger_flags.append("target_lock_foreground_context_review_low_support_frames")
    if (
        _candidate_int_metric(top_candidate, "support_motion_anchor_hits")
        < TARGET_LOCK_ZOOMED_FOREGROUND_SMALL_TARGET_MIN_MOTION_HITS
    ):
        trigger_flags.append("target_lock_foreground_context_review_low_motion_anchor_support")
    if _candidate_int_metric(top_candidate, "multiperson_selected_pair_frame_count") > 0:
        trigger_flags.append("target_lock_foreground_context_review_selected_pair_competitor")
    if not trigger_flags:
        return []

    context_flags: list[str] = []
    if foreground_context:
        context_flags.append("target_lock_foreground_context_review_deprioritized_foreground_competitor")
    if compact_context:
        context_flags.append("target_lock_foreground_context_review_compact_competitor")
    return [*context_flags, *trigger_flags]


def _prefer_complete_body_candidate(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not _is_tiny_stable_candidate(top_candidate):
        return top_candidate
    if _tiny_target_supported_by_deprioritized_zoomed_foreground_context(top_candidate, candidates):
        return top_candidate
    top_confidence = _candidate_confidence(top_candidate)
    complete_candidates = [
        item
        for item in candidates
        if isinstance(item, dict)
        and _is_complete_body_candidate(item)
        and _candidate_confidence(item) >= top_confidence + TARGET_LOCK_COMPLETE_BODY_CONFIDENCE_ADVANTAGE
    ]
    if not complete_candidates:
        return top_candidate
    chosen = max(complete_candidates, key=lambda item: (_candidate_confidence(item), _bbox_area(item["bbox"])))
    flags = chosen.get("quality_flags") if isinstance(chosen.get("quality_flags"), list) else []
    chosen["quality_flags"] = _merge_strings(flags, ["target_lock_complete_body_candidate_preferred_over_tiny_stable"])
    return chosen


def _optional_candidate_float_metric(candidate: dict[str, Any], name: str) -> float | None:
    try:
        value = candidate.get(name)
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_partial_zoomed_body_candidate(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    area = _bbox_area(bbox)
    if area <= 0.0 or area > TARGET_LOCK_PARTIAL_ZOOMED_BODY_MAX_AREA:
        return False
    return (
        _candidate_int_metric(candidate, "support_frame_count") >= TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_FRAMES
        and _candidate_float_metric(candidate, "support_confidence")
        >= TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_CONFIDENCE
        and _candidate_int_metric(candidate, "support_motion_anchor_hits")
        >= TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_MOTION_ANCHOR_HITS
    )


def _is_medium_partial_zoomed_body_candidate(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    area = _bbox_area(bbox)
    height = float(bbox.get("height", 0.0) or 0.0)
    if (
        area <= TARGET_LOCK_PARTIAL_ZOOMED_BODY_MAX_AREA
        or area > TARGET_LOCK_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_AREA
        or height > TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_HEIGHT + 0.04
    ):
        return False
    return (
        _candidate_int_metric(candidate, "support_frame_count") >= TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_FRAMES
        and _candidate_float_metric(candidate, "support_confidence")
        >= TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_CONFIDENCE
        and _candidate_int_metric(candidate, "support_motion_anchor_hits")
        >= TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_MOTION_ANCHOR_HITS
    )


def _is_supported_fuller_zoomed_body_candidate(
    candidate: dict[str, Any],
    top_candidate: dict[str, Any],
) -> bool:
    if candidate is top_candidate or _candidate_id(candidate) == _candidate_id(top_candidate):
        return False
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    flags = candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else []
    if "target_lock_zoomed_foreground_deprioritized_for_stable_small_target" in flags:
        return False
    bbox = candidate.get("bbox")
    top_bbox = top_candidate.get("bbox")
    if not isinstance(bbox, dict) or not isinstance(top_bbox, dict):
        return False
    area = _bbox_area(bbox)
    top_area = _bbox_area(top_bbox)
    height = float(bbox.get("height", 0.0) or 0.0)
    medium_partial_top = _is_medium_partial_zoomed_body_candidate(top_candidate)
    max_fuller_area = (
        TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_AREA
        if medium_partial_top
        else TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_AREA
    )
    min_area_ratio = (
        TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MIN_AREA_RATIO
        if medium_partial_top
        else TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_AREA_RATIO
    )
    if (
        top_area <= 0.0
        or area < TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_AREA
        or area > max_fuller_area
        or height < TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_HEIGHT
        or area / top_area < min_area_ratio
    ):
        return False
    if medium_partial_top and _bbox_center_distance(bbox, top_bbox) > TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_CENTER_DISTANCE:
        return False

    support_count = _candidate_int_metric(candidate, "support_count")
    support_frame_count = _candidate_int_metric(candidate, "support_frame_count")
    support_confidence = _candidate_float_metric(candidate, "support_confidence")
    motion_anchor_hits = _candidate_int_metric(candidate, "support_motion_anchor_hits")
    top_support_count = _candidate_int_metric(top_candidate, "support_count")
    top_support_frame_count = _candidate_int_metric(top_candidate, "support_frame_count")
    top_support_confidence = _candidate_float_metric(top_candidate, "support_confidence")
    top_motion_anchor_hits = _candidate_int_metric(top_candidate, "support_motion_anchor_hits")
    if support_frame_count < max(
        TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_FRAMES,
        top_support_frame_count - 1,
    ):
        return False
    if support_count < max(1.0, top_support_count * TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_RATIO):
        return False
    max_support_confidence_gap = (
        TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_SUPPORT_CONFIDENCE_GAP
        if medium_partial_top
        else TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_SUPPORT_CONFIDENCE_GAP
    )
    if support_confidence < max(
        TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_SUPPORT_CONFIDENCE,
        top_support_confidence - max_support_confidence_gap,
    ):
        return False
    if (
        medium_partial_top
        and _candidate_confidence(candidate)
        < _candidate_confidence(top_candidate) + TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MIN_CONFIDENCE_ADVANTAGE
    ):
        return False
    if motion_anchor_hits < max(
        TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_MOTION_ANCHOR_HITS,
        top_motion_anchor_hits - 1,
    ):
        return False

    support_center_span = _optional_candidate_float_metric(candidate, "support_center_span")
    top_support_center_span = _optional_candidate_float_metric(top_candidate, "support_center_span")
    if support_center_span is None:
        return False
    if support_center_span > TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_SUPPORT_CENTER_SPAN:
        return False
    if (
        top_support_center_span is not None
        and support_center_span
        > top_support_center_span + TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_SUPPORT_CENTER_SPAN_ADVANTAGE
    ):
        return False

    if _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") > (
        _candidate_int_metric(top_candidate, "multiperson_same_anchor_competitor_count")
        + TARGET_LOCK_FULLER_ZOOMED_BODY_MAX_EXTRA_SAME_ANCHOR_COMPETITORS
    ):
        return False
    if _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") > (
        _candidate_int_metric(top_candidate, "multiperson_selected_pair_frame_count") + 1
    ):
        return False
    competitor_risk_increased = (
        _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count")
        > _candidate_int_metric(top_candidate, "multiperson_same_anchor_competitor_count")
        or _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count")
        > _candidate_int_metric(top_candidate, "multiperson_selected_pair_frame_count")
    )
    if competitor_risk_increased:
        stronger_support = support_count >= max(
            top_support_count + 2,
            top_support_count * TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_COMPETITOR_RISK_SUPPORT_RATIO,
        )
        clearer_confidence = (
            support_confidence
            >= top_support_confidence + TARGET_LOCK_FULLER_ZOOMED_BODY_MIN_COMPETITOR_RISK_SUPPORT_CONFIDENCE_ADVANTAGE
        )
        broader_frame_support = support_frame_count > top_support_frame_count
        if not (stronger_support or clearer_confidence or broader_frame_support):
            return False
    return True


def _fuller_zoomed_body_candidate_score(candidate: dict[str, Any]) -> tuple[float, ...]:
    bbox = candidate.get("bbox")
    area = _bbox_area(bbox) if isinstance(bbox, dict) else 0.0
    height = float(bbox.get("height", 0.0) or 0.0) if isinstance(bbox, dict) else 0.0
    support_center_span = _optional_candidate_float_metric(candidate, "support_center_span")
    return (
        float(_candidate_int_metric(candidate, "support_frame_count")),
        float(_candidate_int_metric(candidate, "support_motion_anchor_hits")),
        min(float(_candidate_int_metric(candidate, "support_count")), 60.0),
        _candidate_float_metric(candidate, "support_confidence"),
        _candidate_confidence(candidate),
        min(area, TARGET_LOCK_FULLER_MEDIUM_PARTIAL_ZOOMED_BODY_MAX_AREA),
        min(height, 0.24),
        -float(_candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count")),
        -(support_center_span if support_center_span is not None else 9.0),
    )


def _prefer_fuller_zoomed_body_candidate(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    medium_partial_top = _is_medium_partial_zoomed_body_candidate(top_candidate)
    if not _is_partial_zoomed_body_candidate(top_candidate) and not medium_partial_top:
        return top_candidate
    fuller_candidates = [
        item
        for item in candidates
        if isinstance(item, dict) and _is_supported_fuller_zoomed_body_candidate(item, top_candidate)
    ]
    if not fuller_candidates:
        return top_candidate
    chosen = max(fuller_candidates, key=_fuller_zoomed_body_candidate_score)
    flags = chosen.get("quality_flags") if isinstance(chosen.get("quality_flags"), list) else []
    added_flag = (
        "target_lock_fuller_zoomed_body_candidate_preferred_over_medium_partial_target"
        if medium_partial_top
        else "target_lock_fuller_zoomed_body_candidate_preferred_over_partial_tiny_target"
    )
    chosen["quality_flags"] = _merge_strings(flags, [added_flag])
    return chosen


def _prefer_foreground_review_candidate_over_background_risk(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    top_flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
    background_blocked_flags = [
        str(flag)
        for flag in top_flags
        if str(flag).startswith("target_lock_zoomed_multiperson_background_auto_lock_blocked")
    ] or _stable_zoomed_multiperson_background_auto_lock_blocked_flags(top_candidate)
    if not background_blocked_flags:
        return top_candidate
    if str(top_candidate.get("source") or "") != "yolo_zoomed_content":
        return top_candidate
    top_bbox = top_candidate.get("bbox")
    if not isinstance(top_bbox, dict):
        return top_candidate
    top_area = _bbox_area(top_bbox)
    top_height = float(top_bbox.get("height", 0.0) or 0.0)
    if top_area <= 0.0 or top_height <= 0.0:
        return top_candidate
    if (
        top_area > TARGET_LOCK_REVIEW_BACKGROUND_RISK_MAX_AREA
        or top_height > TARGET_LOCK_REVIEW_BACKGROUND_RISK_MAX_HEIGHT
    ):
        return top_candidate

    foreground_candidates: list[dict[str, Any]] = []
    top_id = _candidate_id(top_candidate)
    for item in candidates:
        if not isinstance(item, dict) or item is top_candidate or _candidate_id(item) == top_id:
            continue
        if str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, dict):
            continue
        area = _bbox_area(bbox)
        width = float(bbox.get("width", 0.0) or 0.0)
        height = float(bbox.get("height", 0.0) or 0.0)
        if (
            area < TARGET_LOCK_REVIEW_FOREGROUND_MIN_AREA
            or width < TARGET_LOCK_REVIEW_FOREGROUND_MIN_WIDTH
            or height < TARGET_LOCK_REVIEW_FOREGROUND_MIN_HEIGHT
            or _candidate_confidence(item) < TARGET_LOCK_REVIEW_FOREGROUND_MIN_CONFIDENCE
            or area / top_area < TARGET_LOCK_REVIEW_FOREGROUND_MIN_AREA_RATIO
            or height / top_height < TARGET_LOCK_REVIEW_FOREGROUND_MIN_HEIGHT_RATIO
            or _candidate_int_metric(item, "multiperson_selected_pair_frame_count")
            > TARGET_LOCK_REVIEW_FOREGROUND_MAX_SELECTED_PAIR_FRAMES
        ):
            continue
        foreground_candidates.append(item)

    if not foreground_candidates:
        return top_candidate
    chosen = max(
        foreground_candidates,
        key=lambda item: (
            _candidate_confidence(item),
            _bbox_area(item["bbox"]),
            float(_candidate_int_metric(item, "support_motion_anchor_hits")),
        ),
    )
    flags = chosen.get("quality_flags") if isinstance(chosen.get("quality_flags"), list) else []
    chosen["quality_flags"] = _merge_strings(
        flags,
        [
            "target_lock_foreground_manual_review_candidate_preferred_over_background_risk",
            "target_lock_auto_lock_blocked_by_manual_review",
        ],
    )
    return chosen


def _is_wide_partial_review_candidate(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    if width <= 0.0 or height <= 0.0:
        return False
    area = _bbox_area(bbox)
    aspect_ratio = width / height
    return (
        TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_AREA <= area <= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_AREA
        and height <= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_HEIGHT
        and aspect_ratio >= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_ASPECT_RATIO
        and _candidate_confidence(candidate) <= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_CONFIDENCE
        and _candidate_int_metric(candidate, "support_count") >= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_SUPPORT
        and _candidate_int_metric(candidate, "support_frame_count") >= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_SUPPORT_FRAMES
        and _candidate_float_metric(candidate, "support_confidence")
        <= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MAX_SUPPORT_CONFIDENCE
        and _candidate_int_metric(candidate, "multiperson_ambiguous_frame_count")
        >= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_AMBIGUOUS_FRAMES
        and _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count")
        >= TARGET_LOCK_REVIEW_WIDE_PARTIAL_MIN_SELECTED_PAIR_FRAMES
    )


def _is_supported_narrow_skater_review_candidate(
    candidate: dict[str, Any],
    top_candidate: dict[str, Any],
) -> bool:
    if candidate is top_candidate or _candidate_id(candidate) == _candidate_id(top_candidate):
        return False
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    top_bbox = top_candidate.get("bbox")
    if not isinstance(bbox, dict) or not isinstance(top_bbox, dict):
        return False
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    if width <= 0.0 or height <= 0.0:
        return False
    area = _bbox_area(bbox)
    top_area = _bbox_area(top_bbox)
    if top_area <= 0.0:
        return False
    aspect_ratio = width / height
    if (
        height < TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_HEIGHT
        or width > TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_WIDTH
        or aspect_ratio > TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_ASPECT_RATIO
        or area > top_area * TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_AREA_RATIO
        or _bbox_center_distance(bbox, top_bbox) < TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_CENTER_DISTANCE
    ):
        return False

    top_support_count = _candidate_int_metric(top_candidate, "support_count")
    top_support_frame_count = _candidate_int_metric(top_candidate, "support_frame_count")
    top_support_confidence = _candidate_float_metric(top_candidate, "support_confidence")
    top_motion_anchor_hits = _candidate_int_metric(top_candidate, "support_motion_anchor_hits")
    support_count = _candidate_int_metric(candidate, "support_count")
    support_frame_count = _candidate_int_metric(candidate, "support_frame_count")
    support_confidence = _candidate_float_metric(candidate, "support_confidence")
    motion_anchor_hits = _candidate_int_metric(candidate, "support_motion_anchor_hits")
    return (
        support_count >= max(1, top_support_count - TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_SUPPORT_GAP)
        and support_frame_count >= max(
            TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_SUPPORT_FRAMES,
            top_support_frame_count - TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_SUPPORT_FRAME_GAP,
        )
        and support_confidence
        >= top_support_confidence + TARGET_LOCK_REVIEW_NARROW_SKATER_MIN_SUPPORT_CONFIDENCE_ADVANTAGE
        and _candidate_confidence(candidate)
        >= _candidate_confidence(top_candidate) - TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_CONFIDENCE_GAP
        and motion_anchor_hits >= max(0, top_motion_anchor_hits - TARGET_LOCK_REVIEW_NARROW_SKATER_MAX_MOTION_HIT_GAP)
    )


def _prefer_narrow_review_candidate_over_wide_partial(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not _is_wide_partial_review_candidate(top_candidate):
        return top_candidate
    narrow_candidates = [
        item
        for item in candidates
        if isinstance(item, dict) and _is_supported_narrow_skater_review_candidate(item, top_candidate)
    ]
    if not narrow_candidates:
        return top_candidate
    chosen = max(
        narrow_candidates,
        key=lambda item: (
            _candidate_float_metric(item, "support_confidence"),
            _candidate_int_metric(item, "support_count"),
            _candidate_confidence(item),
            _candidate_int_metric(item, "support_frame_count"),
            _bbox_area(item["bbox"]),
        ),
    )
    top_flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
    top_candidate["quality_flags"] = _merge_strings(
        top_flags,
        ["target_lock_wide_partial_review_candidate_deprioritized_for_narrow_skater"],
    )
    flags = chosen.get("quality_flags") if isinstance(chosen.get("quality_flags"), list) else []
    chosen["quality_flags"] = _merge_strings(
        flags,
        ["target_lock_narrow_skater_review_candidate_preferred_over_wide_partial"],
    )
    return chosen


def _is_tall_multiperson_review_risk_candidate(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    if width <= 0.0 or height <= 0.0:
        return False
    aspect_ratio = width / height
    return (
        height >= TARGET_LOCK_REVIEW_TALL_MULTIPERSON_MIN_HEIGHT
        and width <= TARGET_LOCK_REVIEW_TALL_MULTIPERSON_MAX_WIDTH
        and aspect_ratio <= TARGET_LOCK_REVIEW_TALL_MULTIPERSON_MAX_ASPECT_RATIO
        and _candidate_int_metric(candidate, "multiperson_selected_pair_frame_count") > 0
        and _candidate_int_metric(candidate, "multiperson_same_anchor_competitor_count") > 0
        and _candidate_int_metric(candidate, "multiperson_other_frame_ambiguous_count") > 0
    )


def _is_supported_compact_motion_review_candidate(
    candidate: dict[str, Any],
    top_candidate: dict[str, Any],
) -> bool:
    if candidate is top_candidate or _candidate_id(candidate) == _candidate_id(top_candidate):
        return False
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    bbox = candidate.get("bbox")
    top_bbox = top_candidate.get("bbox")
    if not isinstance(bbox, dict) or not isinstance(top_bbox, dict):
        return False
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    area = _bbox_area(bbox)
    top_area = _bbox_area(top_bbox)
    top_height = float(top_bbox.get("height", 0.0) or 0.0)
    if (
        width < TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_WIDTH
        or height < TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_HEIGHT
        or area < TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_AREA
        or top_area <= 0.0
        or top_height <= 0.0
        or area > top_area * TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_AREA_RATIO
        or height > top_height * TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_HEIGHT_RATIO
        or _bbox_center_distance(bbox, top_bbox) < TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_CENTER_DISTANCE
    ):
        return False

    support_count = _candidate_int_metric(candidate, "support_count")
    support_frame_count = _candidate_int_metric(candidate, "support_frame_count")
    support_confidence = _candidate_float_metric(candidate, "support_confidence")
    motion_anchor_hits = _candidate_int_metric(candidate, "support_motion_anchor_hits")
    top_support_count = _candidate_int_metric(top_candidate, "support_count")
    top_support_frame_count = _candidate_int_metric(top_candidate, "support_frame_count")
    top_support_confidence = _candidate_float_metric(top_candidate, "support_confidence")
    top_motion_anchor_hits = _candidate_int_metric(top_candidate, "support_motion_anchor_hits")
    return (
        support_count >= top_support_count + TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_SUPPORT_ADVANTAGE
        and support_frame_count
        >= max(1, top_support_frame_count - TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_SUPPORT_FRAME_GAP)
        and support_confidence
        >= top_support_confidence + TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_SUPPORT_CONFIDENCE_ADVANTAGE
        and _candidate_confidence(candidate)
        >= _candidate_confidence(top_candidate) - TARGET_LOCK_REVIEW_COMPACT_MOTION_MAX_CONFIDENCE_GAP
        and motion_anchor_hits >= TARGET_LOCK_REVIEW_COMPACT_MOTION_MIN_MOTION_HITS
        and motion_anchor_hits >= max(0, top_motion_anchor_hits - 1)
    )


def _prefer_compact_motion_review_candidate_over_tall_multiperson_risk(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not _is_tall_multiperson_review_risk_candidate(top_candidate):
        return top_candidate
    compact_candidates = [
        item
        for item in candidates
        if isinstance(item, dict) and _is_supported_compact_motion_review_candidate(item, top_candidate)
    ]
    if not compact_candidates:
        return top_candidate
    chosen = max(
        compact_candidates,
        key=lambda item: (
            _candidate_float_metric(item, "support_confidence"),
            _candidate_int_metric(item, "support_count"),
            _candidate_int_metric(item, "support_frame_count"),
            _candidate_confidence(item),
            -_candidate_int_metric(item, "multiperson_same_anchor_competitor_count"),
            -_bbox_area(item["bbox"]),
        ),
    )
    top_flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
    top_candidate["quality_flags"] = _merge_strings(
        top_flags,
        ["target_lock_tall_multiperson_review_candidate_deprioritized_for_compact_motion"],
    )
    flags = chosen.get("quality_flags") if isinstance(chosen.get("quality_flags"), list) else []
    chosen["quality_flags"] = _merge_strings(
        flags,
        ["target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk"],
    )
    return chosen


def _normalized_detected_candidates(candidates: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates or [], start=1):
        if not isinstance(raw, dict) or not isinstance(raw.get("bbox"), dict):
            continue
        try:
            confidence = float(raw.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        item = dict(raw)
        item["id"] = _candidate_id(item) or f"candidate_detected_{index}"
        item["confidence"] = round(confidence, 4)
        item["source"] = str(item.get("source") or "detector")
        normalized.append(item)
    normalized.sort(key=_candidate_sort_key, reverse=True)
    return normalized


def _merge_candidate_lists(*sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        for item in source:
            candidate_id = _candidate_id(item)
            if not candidate_id or candidate_id in seen:
                continue
            merged.append(item)
            seen.add(candidate_id)
    return merged


def _bbox_center(bbox: dict[str, Any]) -> tuple[float, float]:
    return (
        float(bbox.get("x", 0.0) or 0.0) + float(bbox.get("width", 0.0) or 0.0) / 2.0,
        float(bbox.get("y", 0.0) or 0.0) + float(bbox.get("height", 0.0) or 0.0) / 2.0,
    )


def _bbox_area(bbox: dict[str, Any]) -> float:
    return max(0.0, float(bbox.get("width", 0.0) or 0.0)) * max(0.0, float(bbox.get("height", 0.0) or 0.0))


def _bbox_intersection_area(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1 = float(a.get("x", 0.0) or 0.0)
    ay1 = float(a.get("y", 0.0) or 0.0)
    ax2 = ax1 + float(a.get("width", 0.0) or 0.0)
    ay2 = ay1 + float(a.get("height", 0.0) or 0.0)
    bx1 = float(b.get("x", 0.0) or 0.0)
    by1 = float(b.get("y", 0.0) or 0.0)
    bx2 = bx1 + float(b.get("width", 0.0) or 0.0)
    by2 = by1 + float(b.get("height", 0.0) or 0.0)
    return max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))


def _bbox_iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    intersection = _bbox_intersection_area(a, b)
    if intersection <= 0.0:
        return 0.0
    union = _bbox_area(a) + _bbox_area(b) - intersection
    return intersection / union if union > 0.0 else 0.0


def _bbox_min_containment(a: dict[str, Any], b: dict[str, Any]) -> float:
    intersection = _bbox_intersection_area(a, b)
    smaller_area = min(_bbox_area(a), _bbox_area(b))
    return intersection / smaller_area if smaller_area > 0.0 else 0.0


def _bbox_center_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax, ay = _bbox_center(a)
    bx, by = _bbox_center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _safe_anchor_index(candidate: dict[str, Any]) -> int:
    try:
        value = candidate.get("anchor_index")
        if value is None or value == "":
            return 999999
        return int(value)
    except (TypeError, ValueError):
        return 999999


def _motion_anchor_frame_names(motion_scores: dict[str, Any] | None, *, limit: int = TARGET_LOCK_MOTION_ANCHOR_TOP_N) -> list[str]:
    if not isinstance(motion_scores, dict):
        return []
    selected = [item for item in motion_scores.get("selected", []) if isinstance(item, dict)]

    def sort_key(item: dict[str, Any]) -> tuple[float, float]:
        try:
            motion_score = float(item.get("motion_score") or 0.0)
        except (TypeError, ValueError):
            motion_score = 0.0
        try:
            timestamp = float(item.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            timestamp = 0.0
        return motion_score, -timestamp

    selected.sort(key=sort_key, reverse=True)
    frame_names: list[str] = []
    for item in selected[:limit]:
        frame_id = item.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            continue
        frame_name = frame_id if frame_id.endswith(".jpg") else f"{frame_id}.jpg"
        if frame_name not in frame_names:
            frame_names.append(frame_name)
    return frame_names


def _candidate_support_diagnostics(
    anchor: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    motion_anchor_frames: Sequence[str] = (),
) -> dict[str, Any]:
    support = [item for item in candidates if _candidate_matches_anchor(item, anchor)]
    if not support:
        return {
            "support_anchor_frames": [],
            "support_center_span": None,
            "support_avg_area": None,
            "support_motion_anchor_hits": 0,
        }
    support.sort(key=lambda item: (_safe_anchor_index(item), str(item.get("anchor_frame") or "")))
    centers: list[tuple[float, float]] = []
    areas: list[float] = []
    frames: list[str] = []
    for item in support:
        bbox = item.get("bbox")
        if not isinstance(bbox, dict):
            continue
        centers.append(_bbox_center(bbox))
        areas.append(_bbox_area(bbox))
        frame = str(item.get("anchor_frame") or "").strip()
        if frame and frame not in frames:
            frames.append(frame)
    if centers:
        xs = [point[0] for point in centers]
        ys = [point[1] for point in centers]
        center_span = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
    else:
        center_span = None
    motion_frame_set = set(motion_anchor_frames)
    return {
        "support_anchor_frames": frames[:TARGET_LOCK_SUPPORT_FRAME_LIST_LIMIT],
        "support_center_span": round(center_span, 4) if center_span is not None else None,
        "support_avg_area": round(sum(areas) / len(areas), 6) if areas else None,
        "support_motion_anchor_hits": sum(1 for frame in frames if frame in motion_frame_set),
    }


def _merge_support_diagnostics(
    existing: dict[str, Any],
    computed: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(computed)
    existing_frames = existing.get("support_anchor_frames")
    if isinstance(existing_frames, list) and existing_frames:
        merged["support_anchor_frames"] = existing_frames[:TARGET_LOCK_SUPPORT_FRAME_LIST_LIMIT]

    for key in ("support_center_span", "support_avg_area"):
        try:
            existing_value = float(existing.get(key))
            computed_value = float(computed.get(key))
        except (TypeError, ValueError):
            if existing.get(key) is not None:
                merged[key] = existing.get(key)
            continue
        merged[key] = round(max(existing_value, computed_value), 6 if key == "support_avg_area" else 4)

    try:
        existing_hits = int(existing.get("support_motion_anchor_hits", 0) or 0)
    except (TypeError, ValueError):
        existing_hits = 0
    try:
        computed_hits = int(computed.get("support_motion_anchor_hits", 0) or 0)
    except (TypeError, ValueError):
        computed_hits = 0
    merged["support_motion_anchor_hits"] = max(existing_hits, computed_hits)
    return merged


def _enrich_candidate_support_diagnostics(
    candidates: Sequence[dict[str, Any]],
    motion_scores: dict[str, Any] | None = None,
) -> None:
    motion_anchor_frames = _motion_anchor_frame_names(motion_scores)
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("bbox"), dict):
            continue
        diagnostics = _candidate_support_diagnostics(candidate, candidates, motion_anchor_frames)
        candidate.update(_merge_support_diagnostics(candidate, diagnostics))
        candidate.update(_zoomed_multiperson_diagnostics(candidate, candidates))


def target_preview_anchor_frame_indices(
    frame_names: Sequence[str],
    motion_scores: dict[str, Any] | None = None,
) -> list[int]:
    frame_count = len(frame_names)
    if frame_count <= 0:
        return []
    indices: list[int] = []
    for fraction in TARGET_PREVIEW_ANCHOR_FRACTIONS:
        index = round((frame_count - 1) * fraction)
        if index not in indices:
            indices.append(index)

    if isinstance(motion_scores, dict):
        frame_name_to_index = {frame_name: index for index, frame_name in enumerate(frame_names)}
        for frame_name in _motion_anchor_frame_names(motion_scores):
            index = frame_name_to_index.get(frame_name)
            if index is not None and index not in indices:
                indices.append(index)
    return indices


def _candidate_matches_anchor(candidate: dict[str, Any], anchor: dict[str, Any]) -> bool:
    candidate_bbox = candidate.get("bbox")
    anchor_bbox = anchor.get("bbox")
    if not isinstance(candidate_bbox, dict) or not isinstance(anchor_bbox, dict):
        return False
    candidate_area = _bbox_area(candidate_bbox)
    anchor_area = _bbox_area(anchor_bbox)
    if candidate_area <= 0.0 or anchor_area <= 0.0:
        return False
    area_ratio = candidate_area / anchor_area
    center_distance = _bbox_center_distance(candidate_bbox, anchor_bbox)
    if str(candidate.get("source") or "") == "yolo_zoomed_content" and str(anchor.get("source") or "") == "yolo_zoomed_content":
        if center_distance > TARGET_PREVIEW_ZOOMED_CENTER_DISTANCE:
            return False
        max_area = max(candidate_area, anchor_area)
        min_area = min(candidate_area, anchor_area)
        size_mismatch = area_ratio > TARGET_PREVIEW_ZOOMED_SIZE_MISMATCH_AREA_RATIO or area_ratio < 1.0 / TARGET_PREVIEW_ZOOMED_SIZE_MISMATCH_AREA_RATIO
        tiny_to_person = min_area <= TARGET_PREVIEW_ZOOMED_TINY_AREA and max_area >= TARGET_PREVIEW_ZOOMED_TINY_TO_PERSON_AREA
        if center_distance > TARGET_PREVIEW_ZOOMED_SIZE_MISMATCH_CENTER_DISTANCE and (size_mismatch or tiny_to_person):
            return False
    return (
        TARGET_PREVIEW_AREA_RATIO_RANGE[0] <= area_ratio <= TARGET_PREVIEW_AREA_RATIO_RANGE[1]
        and center_distance <= TARGET_PREVIEW_CENTER_DISTANCE
    )


def candidate_matches_target_anchor(candidate: dict[str, Any], anchor: dict[str, Any]) -> bool:
    """Public wrapper for matching target-lock support candidates to the selected anchor."""

    return _candidate_matches_anchor(candidate, anchor)


def _support_metrics_for_anchor(
    anchor: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> tuple[int, int, float | None]:
    support = [item for item in candidates if _candidate_matches_anchor(item, anchor)]
    per_frame_confidence: dict[str, float] = {}
    for item in support:
        frame = str(item.get("anchor_frame") or item.get("id") or "")
        if not frame:
            continue
        try:
            confidence = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        per_frame_confidence[frame] = max(per_frame_confidence.get(frame, 0.0), confidence)
    support_confidence = (
        round(sum(per_frame_confidence.values()) / len(per_frame_confidence), 4)
        if per_frame_confidence
        else None
    )
    return len(support), len(per_frame_confidence), support_confidence


def _enrich_stable_candidate_support(candidates: Sequence[dict[str, Any]]) -> None:
    for candidate in candidates:
        if not isinstance(candidate, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
            continue
        if not isinstance(candidate.get("bbox"), dict):
            continue
        support_count, support_frame_count, support_confidence = _support_metrics_for_anchor(candidate, candidates)
        if support_count <= 0 or support_confidence is None:
            continue
        try:
            existing_support_count = int(candidate.get("support_count", 0) or 0)
        except (TypeError, ValueError):
            existing_support_count = 0
        try:
            existing_support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
        except (TypeError, ValueError):
            existing_support_frame_count = 0
        try:
            existing_support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            existing_support_confidence = 0.0
        candidate["support_count"] = max(existing_support_count, support_count)
        candidate["support_frame_count"] = max(existing_support_frame_count, support_frame_count)
        candidate["support_confidence"] = max(existing_support_confidence, support_confidence)


def select_stable_target_candidate(anchor_candidates: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    visible = [
        item
        for item in anchor_candidates
        if isinstance(item, dict)
        and isinstance(item.get("bbox"), dict)
        and float(item.get("confidence", 0.0) or 0.0) >= TARGET_PERSON_MIN_CONFIDENCE
    ]
    if not visible:
        return None

    max_anchor_index = max(_safe_anchor_index(item) for item in visible)
    middle_anchor_index = max_anchor_index / 2.0
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    for candidate in visible:
        support = [other for other in visible if _candidate_matches_anchor(other, candidate)]
        support_count = len({str(item.get("anchor_frame") or "") for item in support})
        support_confidence = sum(float(item.get("confidence", 0.0) or 0.0) for item in support) / max(len(support), 1)
        area = _bbox_area(candidate["bbox"])
        source = str(candidate.get("source") or "")
        frame_index = _safe_anchor_index(candidate)
        frame_position_penalty = abs(frame_index - middle_anchor_index) / max(max_anchor_index, 1) * 0.15
        zoom_bonus = 0.75 if source == "yolo_zoomed_content" else 0.0
        foreground_penalty = 2.25 if area >= 0.18 and source != "yolo_zoomed_content" else 0.0
        score = support_count + support_confidence + min(area, 0.12) + zoom_bonus - foreground_penalty - frame_position_penalty
        if score > best_score:
            best = candidate
            best_score = score
    if best is None:
        return None

    chosen = dict(best)
    support_count, support_frame_count, support_confidence = _support_metrics_for_anchor(best, visible)
    chosen["id"] = str(chosen.get("id") or "candidate_auto_stable")
    chosen["source"] = str(chosen.get("source") or "yolo_preview_multi_anchor")
    chosen["support_count"] = support_count
    chosen["support_frame_count"] = support_frame_count
    if support_confidence is not None:
        chosen["support_confidence"] = support_confidence
    chosen.update(_candidate_support_diagnostics(best, visible))
    return chosen


def build_target_preview(
    analysis_id: str,
    frame_names: Sequence[str],
    *,
    existing_target_lock: dict[str, Any] | None = None,
    motion_scores: dict[str, Any] | None = None,
    detected_candidates: Sequence[dict[str, Any]] | None = None,
    analysis_profile: str | None = None,
) -> TargetPreview:
    frame_list = list(frame_names)
    existing_status = (
        str(existing_target_lock.get("status") or "")
        if isinstance(existing_target_lock, dict)
        else ""
    )
    preserve_existing_lock = _is_confirmed_existing_lock(existing_target_lock)
    existing_candidates = (
        [item for item in existing_target_lock.get("candidates", []) if isinstance(item, dict)]
        if isinstance(existing_target_lock, dict) and existing_target_lock.get("candidates")
        else []
    )
    existing_candidate_seed = (
        not existing_status
        and any(str(item.get("source") or "") != "layout_fallback" for item in existing_candidates)
    )
    existing_preview_frame = (
        str(existing_target_lock.get("preview_frame"))
        if (preserve_existing_lock or existing_candidate_seed)
        and isinstance(existing_target_lock, dict)
        and existing_target_lock.get("preview_frame")
        else None
    )
    detected = _normalized_detected_candidates(detected_candidates)
    detected_preview_frame = next(
        (
            str(item.get("anchor_frame"))
            for item in detected
            if isinstance(item.get("anchor_frame"), str) and item.get("anchor_frame") in frame_list
        ),
        None,
    )
    preview_frame = (
        existing_preview_frame
        if existing_preview_frame in frame_list
        else detected_preview_frame or _motion_anchor_frame(frame_list, motion_scores)
    )
    preview_frame_index = frame_list.index(preview_frame) if preview_frame in frame_list else None
    candidates = _merge_candidate_lists(detected, _fallback_candidates(frame_names))

    if existing_candidates:
        candidates = (
            _merge_candidate_lists(existing_candidates, candidates)
            if preserve_existing_lock or (existing_candidate_seed and not detected)
            else _merge_candidate_lists(candidates, existing_candidates)
        )
    _enrich_stable_candidate_support(candidates)
    _enrich_candidate_support_diagnostics(candidates, motion_scores)
    _mark_deprioritized_zoomed_foreground_candidates(candidates)

    visible_candidates = [
        item
        for item in candidates
        if isinstance(item, dict) and float(item.get("confidence", 0.0) or 0.0) >= TARGET_PERSON_MIN_CONFIDENCE
    ]
    visible_ranking_context = list(visible_candidates)
    visible_candidates.sort(
        key=lambda item: _candidate_contextual_rank_score(item, visible_ranking_context),
        reverse=True,
    )
    if not visible_candidates:
        auto_candidate_id = None
        lock_confidence = 0.0
        target_lock_status = "no_person_detected"
    else:
        top_candidate = _prefer_fuller_zoomed_body_candidate(visible_candidates[0], visible_candidates)
        top_candidate = _prefer_complete_body_candidate(top_candidate, visible_candidates)
        top_candidate = _prefer_foreground_review_candidate_over_background_risk(top_candidate, visible_candidates)
        top_candidate = _prefer_narrow_review_candidate_over_wide_partial(top_candidate, visible_candidates)
        top_candidate = _prefer_compact_motion_review_candidate_over_tall_multiperson_risk(
            top_candidate,
            visible_candidates,
        )
        auto_candidate_id = str(top_candidate.get("id") or "") or None
        lock_confidence = float(top_candidate.get("confidence", 0.0) or 0.0)
        stable_zoomed_auto_lock_flags = _stable_zoomed_candidate_auto_lock_flags(top_candidate)
        stable_zoomed_auto_lock = bool(stable_zoomed_auto_lock_flags)
        if stable_zoomed_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, stable_zoomed_auto_lock_flags)
            try:
                support_confidence = float(top_candidate.get("support_confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                support_confidence = 0.0
            if support_confidence > lock_confidence:
                lock_confidence = support_confidence
        tiny_zoomed_manual_review = _tiny_zoomed_candidate_requires_manual_review(top_candidate)
        distant_single_jump_flags = _distant_single_jump_auto_lock_flags(top_candidate, candidates, analysis_profile)
        distant_single_jump_auto_lock = bool(distant_single_jump_flags)
        if distant_single_jump_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, distant_single_jump_flags)
        foreground_contextual_small_review_reason_flags = _foreground_contextual_small_target_review_reason_flags(
            top_candidate,
            candidates,
        )
        foreground_contextual_small_manual_review = bool(foreground_contextual_small_review_reason_flags)
        zoomed_multiperson_flags = _zoomed_multiperson_manual_review_flags(top_candidate, candidates)
        zoomed_multiperson_manual_review = "target_lock_zoomed_multiperson_manual_review" in zoomed_multiperson_flags
        same_anchor_zoomed_multiperson = (
            "target_lock_zoomed_multiperson_manual_review"
            in _zoomed_multiperson_manual_review_flags(top_candidate, candidates, same_anchor_only=True)
        )
        scale_competitor_flags = _zoomed_multiperson_scale_competitor_manual_review_flags(top_candidate, candidates)
        if scale_competitor_flags:
            zoomed_multiperson_flags = _merge_strings(zoomed_multiperson_flags, scale_competitor_flags)
            zoomed_multiperson_manual_review = True
        foreground_background_auto_lock_allowed = (
            zoomed_multiperson_manual_review
            and not scale_competitor_flags
            and "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk"
            not in (top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else [])
            and _stable_zoomed_foreground_with_tiny_background_auto_lock_allowed(top_candidate, candidates)
        )
        foreground_transient_background_auto_lock_allowed = (
            zoomed_multiperson_manual_review
            and not scale_competitor_flags
            and "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk"
            not in (top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else [])
            and _stable_zoomed_foreground_with_transient_background_auto_lock_allowed(top_candidate)
        )
        selected_pair_min_distance = _zoomed_multiperson_selected_pair_min_distance(top_candidate, candidates)
        isolated_zoomed_auto_lock_allowed = (
            zoomed_multiperson_manual_review
            and not scale_competitor_flags
            and "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk"
            not in (top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else [])
            and _stable_zoomed_multiperson_isolated_auto_lock_allowed(top_candidate)
            and (
                selected_pair_min_distance is None
                or selected_pair_min_distance
                >= TARGET_LOCK_ZOOMED_MULTIPERSON_ISOLATED_AUTO_MIN_SELECTED_PAIR_DISTANCE
            )
        )
        clear_compact_auto_lock_allowed = (
            zoomed_multiperson_manual_review
            and not scale_competitor_flags
            and "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk"
            not in (top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else [])
            and _stable_zoomed_multiperson_clear_compact_auto_lock_allowed(top_candidate)
        )
        background_auto_lock_blocked_flags = (
            _stable_zoomed_multiperson_background_auto_lock_blocked_flags(top_candidate)
            if (
                zoomed_multiperson_manual_review
                and not scale_competitor_flags
                and not foreground_background_auto_lock_allowed
                and not foreground_transient_background_auto_lock_allowed
                and not isolated_zoomed_auto_lock_allowed
                and not clear_compact_auto_lock_allowed
            )
            else []
        )
        if (
            zoomed_multiperson_manual_review
            and not scale_competitor_flags
            and not background_auto_lock_blocked_flags
            and "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk"
            not in (top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else [])
            and (
                foreground_background_auto_lock_allowed
                or foreground_transient_background_auto_lock_allowed
                or isolated_zoomed_auto_lock_allowed
                or clear_compact_auto_lock_allowed
                or _stable_zoomed_multiperson_background_auto_lock_allowed(top_candidate)
            )
        ):
            _remove_quality_flags(
                top_candidate,
                [
                    "target_lock_zoomed_multiperson_manual_review",
                    "target_lock_zoomed_multiperson_background_auto_lock_blocked_small_moving_risk",
                    "target_lock_zoomed_multiperson_background_auto_lock_blocked_large_moving_risk",
                    "target_lock_zoomed_multiperson_background_auto_lock_blocked_dispersed_small_risk",
                    "target_lock_stable_zoomed_auto_lock_blocked_by_manual_review",
                    "target_lock_distant_single_jump_auto_lock_blocked_by_manual_review",
                    "target_lock_auto_lock_blocked_by_manual_review",
                ],
            )
            zoomed_multiperson_flags = [
                flag
                for flag in zoomed_multiperson_flags
                if flag != "target_lock_zoomed_multiperson_manual_review"
            ]
            zoomed_multiperson_flags.append("target_lock_zoomed_multiperson_background_auto_lock_allowed")
            if foreground_background_auto_lock_allowed:
                zoomed_multiperson_flags.append(
                    "target_lock_zoomed_multiperson_foreground_background_auto_lock_allowed"
                )
            if foreground_transient_background_auto_lock_allowed:
                zoomed_multiperson_flags.append(
                    "target_lock_zoomed_multiperson_foreground_transient_background_auto_lock_allowed"
                )
            if isolated_zoomed_auto_lock_allowed:
                zoomed_multiperson_flags.append(
                    "target_lock_zoomed_multiperson_isolated_background_auto_lock_allowed"
                )
            if clear_compact_auto_lock_allowed:
                zoomed_multiperson_flags.append(
                    "target_lock_zoomed_multiperson_clear_compact_target_auto_lock_allowed"
                )
            zoomed_multiperson_manual_review = False
        elif background_auto_lock_blocked_flags:
            zoomed_multiperson_flags = _merge_strings(zoomed_multiperson_flags, background_auto_lock_blocked_flags)
        if zoomed_multiperson_manual_review:
            zoomed_multiperson_flags = _merge_strings(
                zoomed_multiperson_flags,
                _zoomed_multiperson_review_reason_flags(top_candidate),
            )
        if zoomed_multiperson_flags:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, zoomed_multiperson_flags)
        if tiny_zoomed_manual_review and not distant_single_jump_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, ["target_lock_tiny_zoomed_low_support_manual_review"])
        if foreground_contextual_small_manual_review and not distant_single_jump_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(
                flags,
                [
                    "target_lock_foreground_context_small_target_manual_review",
                    *foreground_contextual_small_review_reason_flags,
                ],
            )
        manual_review_required = (
            (tiny_zoomed_manual_review and not distant_single_jump_auto_lock)
            or foreground_contextual_small_manual_review
            or zoomed_multiperson_manual_review
            or _has_manual_review_flag(top_candidate)
        )
        if manual_review_required:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            background_auto_lock_was_allowed = any(
                str(flag) in TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_FLAGS
                for flag in flags
            )
            _remove_quality_flags(
                top_candidate,
                [
                    *stable_zoomed_auto_lock_flags,
                    *distant_single_jump_flags,
                    *TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_FLAGS,
                ],
            )
            if background_auto_lock_was_allowed:
                flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
                top_candidate["quality_flags"] = _merge_strings(
                    flags,
                    [TARGET_LOCK_BACKGROUND_AUTO_LOCK_ALLOWED_OVERRIDDEN_FLAG],
                )
            blocked_flags = _auto_lock_blocked_flags(
                stable_zoomed_auto_lock=stable_zoomed_auto_lock,
                distant_single_jump_auto_lock=distant_single_jump_auto_lock,
            )
            if blocked_flags:
                flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
                top_candidate["quality_flags"] = _merge_strings(flags, blocked_flags)
        if (
            lock_confidence < TARGET_LOCK_AUTO_THRESHOLD
            or tiny_zoomed_manual_review
            or manual_review_required
        ) and not stable_zoomed_auto_lock and not distant_single_jump_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, ["target_lock_manual_review_low_confidence"])
        global_auto_lock = (
            lock_confidence >= TARGET_LOCK_AUTO_THRESHOLD
            and not tiny_zoomed_manual_review
            and not manual_review_required
        )
        target_lock_status = (
            "auto_locked"
            if (global_auto_lock or stable_zoomed_auto_lock or distant_single_jump_auto_lock)
            and not manual_review_required
            else "awaiting_manual"
        )
        candidate_ranking_context = list(candidates)
        candidates.sort(
            key=lambda item: (
                1 if _candidate_id(item) == auto_candidate_id else 0,
                _candidate_contextual_rank_score(item, candidate_ranking_context),
            ),
            reverse=True,
        )

    if preserve_existing_lock and isinstance(existing_target_lock, dict):
        auto_candidate_id = str(existing_target_lock.get("selected_candidate_id") or auto_candidate_id or "")
        lock_confidence = float(existing_target_lock.get("lock_confidence", lock_confidence) or lock_confidence)
        target_lock_status = str(existing_target_lock.get("status", target_lock_status))

    _clean_background_auto_lock_allowed_conflicts(candidates, target_lock_status=target_lock_status)

    return TargetPreview(
        preview_frame=preview_frame,
        preview_frame_url=f"/api/frames/{analysis_id}/{preview_frame}" if preview_frame else None,
        preview_frame_index=preview_frame_index,
        auto_candidate_id=auto_candidate_id or None,
        lock_confidence=round(lock_confidence, 4),
        candidates=candidates,
        target_lock_status=target_lock_status,
    )


def _motion_anchor_frame(frame_list: Sequence[str], motion_scores: dict[str, Any] | None) -> str | None:
    if not frame_list:
        return None
    if not isinstance(motion_scores, dict):
        return frame_list[0]

    available = set(frame_list)
    selected = motion_scores.get("selected")
    if not isinstance(selected, list):
        return frame_list[0]

    best_frame: str | None = None
    best_score = float("-inf")
    best_timestamp = float("inf")
    for item in selected:
        if not isinstance(item, dict):
            continue
        frame_id = item.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            continue
        frame_name = frame_id if frame_id.endswith(".jpg") else f"{frame_id}.jpg"
        if frame_name not in available:
            continue
        try:
            score = float(item.get("motion_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            timestamp = float(item.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            timestamp = 0.0
        if score > best_score or (score == best_score and timestamp < best_timestamp):
            best_frame = frame_name
            best_score = score
            best_timestamp = timestamp

    return best_frame or frame_list[0]


def resolve_manual_candidate(
    candidates: Sequence[dict[str, Any]],
    candidate_id: str | None,
    x: float | None,
    y: float | None,
) -> dict[str, Any] | None:
    if candidate_id:
        for candidate in candidates:
            if str(candidate.get("id")) == candidate_id:
                return candidate

    if x is None or y is None:
        return None

    for candidate in candidates:
        bbox = candidate.get("bbox")
        if not isinstance(bbox, dict):
            continue
        left = float(bbox.get("x", 0.0))
        top = float(bbox.get("y", 0.0))
        width = float(bbox.get("width", 0.0))
        height = float(bbox.get("height", 0.0))
        if left <= x <= left + width and top <= y <= top + height:
            return candidate
    return None


def build_target_lock_payload(
    preview: TargetPreview,
    *,
    selected_candidate: dict[str, Any] | None = None,
    manual_bbox: dict[str, Any] | None = None,
    manual: bool = False,
) -> dict[str, Any]:
    if manual_bbox is not None:
        selected_bbox = validate_manual_bbox(manual_bbox)
        return {
            "preview_frame": preview.preview_frame,
            "preview_frame_index": preview.preview_frame_index,
            "candidates": preview.candidates,
            "selected_candidate_id": None,
            "selected_bbox": selected_bbox,
            "lock_confidence": 1.0,
            "status": "manual",
            "manual_override": True,
            "quality_flags": [],
        }

    chosen = selected_candidate
    if chosen is None and preview.auto_candidate_id and preview.target_lock_status == "auto_locked":
        chosen = next((item for item in preview.candidates if str(item.get("id")) == preview.auto_candidate_id), None)
    diagnostic_candidate = chosen
    if diagnostic_candidate is None and preview.auto_candidate_id:
        diagnostic_candidate = next((item for item in preview.candidates if str(item.get("id")) == preview.auto_candidate_id), None)
    quality_flags = (
        diagnostic_candidate.get("quality_flags")
        if isinstance(diagnostic_candidate, dict) and isinstance(diagnostic_candidate.get("quality_flags"), list)
        else []
    )
    preview_frame = preview.preview_frame
    preview_frame_index = preview.preview_frame_index
    if isinstance(chosen, dict):
        candidate_anchor_frame = str(chosen.get("anchor_frame") or "").strip()
        if candidate_anchor_frame:
            preview_frame = candidate_anchor_frame
        try:
            candidate_anchor_index = chosen.get("anchor_index")
            if candidate_anchor_index is not None and candidate_anchor_index != "":
                preview_frame_index = int(candidate_anchor_index)
        except (TypeError, ValueError):
            pass

    return {
        "preview_frame": preview_frame,
        "preview_frame_index": preview_frame_index,
        "candidates": preview.candidates,
        "selected_candidate_id": chosen.get("id") if isinstance(chosen, dict) else preview.auto_candidate_id,
        "selected_bbox": chosen.get("bbox") if isinstance(chosen, dict) else None,
        "lock_confidence": _candidate_effective_lock_confidence(chosen, preview.lock_confidence) if isinstance(chosen, dict) else preview.lock_confidence,
        "status": "locked" if manual else preview.target_lock_status,
        "manual_override": manual,
        "quality_flags": list(quality_flags),
    }


def extract_pose_target_bbox(target_lock: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(target_lock, dict):
        return None
    bbox = target_lock.get("selected_bbox")
    return bbox if isinstance(bbox, dict) else None


def frame_names_from_dir(frames_dir: str | Path) -> list[str]:
    frame_paths = sorted(Path(frames_dir).glob("frame_*.jpg"))
    return [frame_path.name for frame_path in frame_paths]
