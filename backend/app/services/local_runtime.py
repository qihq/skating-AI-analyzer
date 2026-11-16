"""Read-only runtime preflight before trial analysis creates files or records."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
from fastapi import HTTPException
from app.trial import trial_profile


def require_local_runtime() -> None:
    if trial_profile() != "legacy-analysis-preview":
        return
    try:
        for name in ("torch", "torchvision", "ultralytics", "supervision", "mediapipe", "cv2"):
            if importlib.util.find_spec(name) is None:
                raise RuntimeError(f"missing dependency: {name}")
        for name in ("ffmpeg", "ffprobe"):
            if shutil.which(name) is None:
                raise RuntimeError(f"missing executable: {name}")
        manifest = Path(os.getenv("LOCAL_MODEL_MANIFEST", "/models/manifest.json"))
        models = json.loads(manifest.read_text(encoding="utf-8"))
        if not models or {item["role"] for item in models} != {"person", "pose", "pose_detection"}:
            raise RuntimeError("incomplete model manifest")
        for item in models:
            path = Path(item["path"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError(f"missing or changed model: {path}")
        person = next(item for item in models if item["role"] == "person")
        if Path(os.getenv("YOLO_PERSON_MODEL_PATH", "/models/yolov8n.pt")) != Path(person["path"]):
            raise RuntimeError("person model path does not match manifest")
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "local_runtime_unavailable", "message": str(exc)}) from exc


async def recover_interrupted_local_analyses(session_factory=None) -> int:
    """One worker: startup marks interrupted work retryable, preserving existing facts."""
    from app.database import AsyncSessionLocal
    from app.services.segment_reanchor_runtime import recover_interrupted_reanchors
    auxiliary_count = 0
    if trial_profile() == "off":
        auxiliary_count = await recover_interrupted_reanchors(session_factory or AsyncSessionLocal)
    if trial_profile() != "legacy-analysis-preview":
        return auxiliary_count
    from sqlalchemy import select
    from app.models import Analysis
    async with (session_factory or AsyncSessionLocal)() as session:
        rows = (await session.scalars(select(Analysis).where(Analysis.status.in_(
            ["pending", "processing", "extracting_frames", "analyzing", "generating_report"]
        )))).all()
        for row in rows:
            row.status = "failed"
            row.error_code = "UNKNOWN_ERROR"
            row.error_message = "本地任务被服务重启中断；视频和已保存数据保留，请重试。"
            row.error_detail = "local_process_interrupted"
            row.retry_from_stage = "extract_frames"
        await session.commit()
        return auxiliary_count + len(rows)
