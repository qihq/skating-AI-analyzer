#!/usr/bin/env python3
"""重建 ai_skating_analysis_pack 到 v1.1.11。

将 backend/app/services/ 下所有 AI 分析相关源码复制到打包文件夹，
保持原始 import 路径（app.services.X），便于代码审查。

用法: cd skating-analyzer && python ai_skating_analysis_pack/_rebuild.py
"""
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "backend" / "app" / "services"
DST = REPO_ROOT / "ai_skating_analysis_pack" / "src" / "app" / "services"
V2_SRC = REPO_ROOT / "backend" / "app" / "analysis_v2"
V2_DST = REPO_ROOT / "ai_skating_analysis_pack" / "src" / "app" / "analysis_v2"

FILES = [
    "__init__.py",
    "video.py",
    "target_lock.py",
    "bbox_tracker.py",
    "smoothing.py",
    "pose.py",
    "action_profiles.py",
    "jump_features.py",
    "biomechanics.py",
    "bio_context.py",
    "vision.py",
    "vision_path_a.py",
    "vision_path_b.py",
    "vision_dual.py",
    "cross_validator.py",
    "frame_annotator.py",
    "phase_smoother.py",
    "report.py",
    "providers.py",
    "analysis_errors.py",
    "pipeline_version.py",
    "vision_vote_config.py",
    "snowball.py",
    "memory_suggest.py",
    "plan.py",
    "vision_prompt_templates.py",
]
V2_FILES = [
    "__init__.py",
    "timebase.py",
    "contracts.py",
    "identity.py",
    "event_proposals.py",
    "facts.py",
    "action_classification.py",
    "event_label_facts.py",
    "profile_eligibility.py",
    "profile_moments.py",
    "moment_selectors.py",
    "event_moment_facts.py",
    "rotation.py",
    "rotation_facts.py",
    # Iteration 14 claim/facts boundary.  Keep the standalone snapshot's
    # V2 modules generated from the backend source of truth; these modules
    # are imported by the generated vision/report/memory services.
    "capabilities.py",
    "claim_fusion.py",
    "claim_report.py",
    "comparison.py",
    "config.py",
    "dependency_boundary.py",
    "detection.py",
    "fact_consumers.py",
    "fingerprints.py",
    "fusion_inputs.py",
    "manifest.py",
    "orchestration.py",
    "path_review.py",
    "pose_v2.py",
    "presentation.py",
    "status.py",
    # Iteration 15 end-to-end Shadow orchestration.  These modules are part
    # of the generated V2 snapshot so standalone consumers see the same
    # checkpoint/queue/contracts implementation as the backend.  They do
    # not write legacy result fields; callers still opt into Shadow through
    # the parent-authorized runtime API.
    "contamination_inventory.py",
    "shadow_contracts.py",
    "shadow_dispatch.py",
    # Parent-authorized API execution bridge.  Keep this in the standalone
    # snapshot so consumers that enqueue Shadow runs use the same bounded
    # coordinator implementation as the backend.
    "shadow_execution.py",
    "shadow_pipeline.py",
    "shadow_store.py",
]

def main():
    DST.mkdir(parents=True, exist_ok=True)
    ok, miss = 0, 0
    for f in FILES:
        s, d = SRC / f, DST / f
        if s.exists():
            shutil.copy2(s, d)
            ok += 1
            print(f"  OK  {f}")
        else:
            miss += 1
            print(f"  MISS {f}")
    V2_DST.mkdir(parents=True, exist_ok=True)
    for f in V2_FILES:
        s, d = V2_SRC / f, V2_DST / f
        if s.exists():
            shutil.copy2(s, d)
            ok += 1
            print(f"  OK  analysis_v2/{f}")
        else:
            miss += 1
            print(f"  MISS analysis_v2/{f}")
    print(f"\nCopied {ok} files, {miss} missing.")

if __name__ == "__main__":
    main()
