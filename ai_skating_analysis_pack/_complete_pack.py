#!/usr/bin/env python3
"""补全 src/app/services/ 目录：将旧版文件复制为基线。

运行方式: cd skating-analyzer && python ai_skating_analysis_pack/_complete_pack.py
之后再运行 python ai_skating_analysis_pack/_rebuild.py 更新到最新版本。
"""
import shutil
from pathlib import Path

PACK = Path(__file__).resolve().parent
DST = PACK / "src" / "app" / "services"

MAPPING = {
    "src/preprocessing/video.py": "video.py",
    "src/preprocessing/target_lock.py": "target_lock.py",
    "src/pose_estimation/pose.py": "pose.py",
    "src/action_recognition/action_profiles.py": "action_profiles.py",
    "src/action_recognition/phase_smoother.py": "phase_smoother.py",
    "src/quality_assessment/biomechanics.py": "biomechanics.py",
    "src/quality_assessment/vision.py": "vision.py",
    "src/quality_assessment/report.py": "report.py",
    "src/utils/providers.py": "providers.py",
    "src/utils/analysis_errors.py": "analysis_errors.py",
    "src/utils/snowball.py": "snowball.py",
    "src/utils/memory_suggest.py": "memory_suggest.py",
}

def main():
    DST.mkdir(parents=True, exist_ok=True)
    for src_rel, dst_name in MAPPING.items():
        src = PACK / src_rel
        dst = DST / dst_name
        if dst.exists():
            print(f"  SKIP (already exists): {dst_name}")
            continue
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  COPY: {src_rel} -> services/{dst_name}")
        else:
            print(f"  MISS: {src_rel}")

    # 也复制 plan.py 如果存在
    plan_src = PACK / "src" / "utils" / "plan.py"
    plan_dst = DST / "plan.py"
    if not plan_dst.exists() and plan_src.exists():
        shutil.copy2(plan_src, plan_dst)
        print("  COPY: utils/plan.py -> services/plan.py")

    print("\nDone. Now run _rebuild.py to update to latest backend version.")

if __name__ == "__main__":
    main()
