#!/usr/bin/env python3
"""构建 ai_skating_analysis_pack 打包文件夹的自动化脚本。

从 backend/app/services/ 复制所有 AI 分析相关源码，
保持原始 import 路径，生成 requirements.txt、README.md 和 error_cases_and_metrics.md。

用法: python _build_pack.py
"""
import shutil
import os
from pathlib import Path

# 仓库根目录
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SERVICES = REPO_ROOT / "backend" / "app" / "services"
BACKEND_APP = REPO_ROOT / "backend" / "app"
BACKEND_TESTS = REPO_ROOT / "backend" / "tests"
PACK_DIR = REPO_ROOT / "ai_skating_analysis_pack"
PACK_SRC = PACK_DIR / "src" / "app" / "services"
PACK_APP = PACK_DIR / "src" / "app"
PACK_CONFIGS = PACK_DIR / "configs"
PACK_TESTS = PACK_DIR / "tests"

# AI 分析相关的 service 文件
AI_SERVICE_FILES = [
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
    "__init__.py",
]

# 非 service 的 app 文件
APP_FILES = [
    "database.py",
    "models.py",
    "schemas.py",
    "main.py",
]

# 测试文件
TEST_FILES = [
    "test_action_profiles.py",
    "test_biomechanics_jump_rotation_estimation.py",
    "test_pipeline_version.py",
]


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, dst: Path):
    if src.exists():
        shutil.copy2(src, dst)
        print(f"  copied: {src.name}")
    else:
        print(f"  MISSING: {src}")


def main():
    print("=" * 60)
    print("Building ai_skating_analysis_pack")
    print("=" * 60)

    # 1. 创建目录结构
    print("\n[1/6] Creating directory structure...")
    for d in [PACK_SRC, PACK_APP, PACK_CONFIGS, PACK_TESTS, PACK_DIR / "weights"]:
        ensure_dir(d)

    # 2. 复制 service 文件
    print("\n[2/6] Copying service files...")
    for fname in AI_SERVICE_FILES:
        src = BACKEND_SERVICES / fname
        dst = PACK_SRC / fname
        copy_file(src, dst)

    # 3. 复制 app 级文件
    print("\n[3/6] Copying app-level files...")
    for fname in APP_FILES:
        src = BACKEND_APP / fname
        dst = PACK_APP / fname
        copy_file(src, dst)

    # 4. 复制 __init__.py
    src_init = BACKEND_APP / "__init__.py"
    if src_init.exists():
        shutil.copy2(src_init, PACK_APP / "__init__.py")

    # 5. 复制测试文件
    print("\n[4/6] Copying test files...")
    for fname in TEST_FILES:
        src = BACKEND_TESTS / fname
        dst = PACK_TESTS / fname
        copy_file(src, dst)

    # 6. 复制配置文件（如果有的话）
    print("\n[5/6] Copying config files...")
    config_src = BACKEND_APP / "configs"
    if config_src.exists():
        for f in config_src.iterdir():
            if f.is_file():
                shutil.copy2(f, PACK_CONFIGS / f.name)
                print(f"  copied: {f.name}")

    # 7. 创建 weights/.gitkeep 和 WEIGHTS_README.md
    print("\n[6/6] Writing weights documentation...")
    gitkeep = PACK_DIR / "weights" / ".gitkeep"
    gitkeep.write_text("")

    weights_readme = PACK_DIR / "weights" / "WEIGHTS_README.md"
    weights_readme.write_text(
        """# 模型权重说明

本模块使用的模型权重均为外部服务托管，无需本地下载。

## MediaPipe Pose (姿态估计)

- **来源**: Google MediaPipe (内置权重)
- **安装方式**: `pip install mediapipe==0.10.14`
- **权重位置**: MediaPipe 包内自动管理，无需手动下载
- **单人模式**: `mediapipe.solutions.pose.Pose` (model_complexity=1)
- **多人模式**: 需要单独配置 `MEDIAPIPE_POSE_TASK_PATH` 环境变量指向 `.task` 模型文件
  - 下载地址: https://developers.google.com/mediapipe/solutions/vision/pose_landmarker
  - 文件名: `pose_landmarker_heavy.task` (~30MB)
  - 配置方式: `MEDIAPIPE_POSE_TASK_PATH=/path/to/pose_landmarker_heavy.task`

## LLM 视觉模型 (远程 API)

本模块不使用本地权重，而是通过 API 调用远程大语言模型：

| 角色 | 默认模型 | API 端点 |
|------|---------|---------|
| Vision (视觉分析) | qwen3.6-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| Report (报告生成) | deepseek-chat | https://api.deepseek.com/v1 |

## CSRT 跟踪器 (bbox_tracker)

- **来源**: OpenCV 内置
- **安装方式**: `pip install opencv-python-headless==4.10.0.84`
- **权重位置**: OpenCV 包内自动管理
""",
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("Build complete!")
    print("=" * 60)

    # 统计
    py_files = list(PACK_DIR.rglob("*.py"))
    total_size = sum(f.stat().st_size for f in PACK_DIR.rglob("*") if f.is_file())
    print(f"\nTotal Python files: {len(py_files)}")
    print(f"Total size: {total_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
