#!/usr/bin/env python3
"""重建 ai_skating_analysis_pack 到 v1.1.11。

将 backend/app/services/ 下所有 AI 分析相关源码复制到打包文件夹，
保持原始 import 路径（app.services.X），便于代码审查。

用法: cd skating-analyzer && python ai_skating_analysis_pack/_rebuild.py
"""
import shutil
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "backend" / "app" / "services"
DST = REPO_ROOT / "ai_skating_analysis_pack" / "src" / "app" / "services"

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
    print(f"\nCopied {ok} files, {miss} missing.")

if __name__ == "__main__":
    main()
