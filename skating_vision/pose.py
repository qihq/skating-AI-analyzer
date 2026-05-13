"""姿态检测：MediaPipe 多人姿态 + 目标锁定。已解耦，可独立使用。"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any

from skating_vision.target_lock import extract_pose_target_bbox

logger = logging.getLogger(__name__)

_project_root = Path(__file__).resolve().parent.parent

LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]

POSE_CONNECTIONS = [
    [11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24],
    [23, 25], [25, 27], [27, 29], [29, 31], [24, 26], [26, 28], [28, 30], [30, 32], [0, 11], [0, 12],
]

_pose_logged = False


def _pose_config() -> tuple[int, str]:
    return int(os.getenv("POSE_NUM_POSES", "4")), os.getenv("MEDIAPIPE_POSE_TASK_PATH", "").strip()


def _resolve_model(path_str: str, root: Path | None = None) -> Path | None:
    if not path_str:
        return None
    r = root or _project_root
    p = Path(path_str)
    candidates = [p]
    if path_str.startswith(("/", "\\")):
        candidates.append(r / path_str.lstrip("/\\"))
    elif not p.is_absolute():
        candidates.append(r / p)
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


def get_pose_runtime_status(project_root: Path | None = None) -> dict[str, Any]:
    np, mp = _pose_config()
    cfg = bool(mp)
    rp = _resolve_model(mp, project_root) if cfg else None
    ex = bool(rp and rp.exists())
    if cfg and ex:
        mode, reason = "multi_pose", "configured"
    elif cfg:
        mode, reason = "fallback_single_pose", "missing_model_file"
    else:
        mode, reason = "fallback_single_pose", "model_path_not_set"
    return {"mode": mode, "configured": cfg, "model_path": mp or None, "model_exists": ex, "num_poses": np, "reason": reason}


def log_pose_runtime_mode(project_root: Path | None = None) -> None:
    global _pose_logged
    if _pose_logged:
        return
    s = get_pose_runtime_status(project_root)
    if s["reason"] == "model_path_not_set":
        logger.info("pose mode = fallback_single_pose (MEDIAPIPE_POSE_TASK_PATH is not set)")
    elif s["reason"] == "missing_model_file":
        logger.warning("pose mode = fallback_single_pose (model file not found at %s)", s["model_path"])
    else:
        logger.info("pose mode = multi_pose (model=%s, num_poses=%s)", s["model_path"], s["num_poses"])
    _pose_logged = True


def _empty() -> dict[str, Any]:
    return {"connections": POSE_CONNECTIONS, "frames": []}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def _crop_bounds(iw: int, ih: int, bbox: dict[str, float] | None) -> tuple[int, int, int, int]:
    if not bbox:
        return 0, 0, iw, ih
    x = int(max(0.0, min(1.0, float(bbox.get("x", 0.0)))) * iw)
    y = int(max(0.0, min(1.0, float(bbox.get("y", 0.0)))) * ih)
    w = int(max(0.05, min(1.0, float(bbox.get("width", 1.0)))) * iw)
    h = int(max(0.05, min(1.0, float(bbox.get("height", 1.0)))) * ih)
    return x, y, min(iw, x + max(w, 1)), min(ih, y + max(h, 1))


def _bbox_from_landmarks(lm: list[Any]) -> dict[str, float] | None:
    xs = [float(l.x) for l in lm]
    ys = [float(l.y) for l in lm]
    if not xs or not ys:
        return None
    return {
        "x": round(_clamp(min(xs), 0.0, 1.0), 4), "y": round(_clamp(min(ys), 0.0, 1.0), 4),
        "width": round(max(0.05, _clamp(max(xs), 0.0, 1.0) - _clamp(min(xs), 0.0, 1.0)), 4),
        "height": round(max(0.05, _clamp(max(ys), 0.0, 1.0) - _clamp(min(ys), 0.0, 1.0)), 4),
    }


def _bbox_center(b: dict[str, float] | None) -> tuple[float, float]:
    if not b:
        return 0.5, 0.5
    return float(b.get("x", 0.0)) + float(b.get("width", 0.0)) / 2, float(b.get("y", 0.0)) + float(b.get("height", 0.0)) / 2


def _bbox_area(b: dict[str, float] | None) -> float:
    return float(b.get("width", 0.0)) * float(b.get("height", 0.0)) if b else 0.0


def _bbox_iou(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
    if not a or not b:
        return 0.0
    ax1, ay1 = float(a.get("x", 0.0)), float(a.get("y", 0.0))
    ax2, ay2 = ax1 + float(a.get("width", 0.0)), ay1 + float(a.get("height", 0.0))
    bx1, by1 = float(b.get("x", 0.0)), float(b.get("y", 0.0))
    bx2, by2 = bx1 + float(b.get("width", 0.0)), by1 + float(b.get("height", 0.0))
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = _bbox_area(a) + _bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def _vis_sum(lm: list[Any]) -> float:
    return sum(float(getattr(l, "visibility", 0.0) or 0.0) for l in lm)


def _map_kps(lm: list[Any], cl: int, ct: int, cw: int, ch: int, iw: int, ih: int) -> list[dict[str, Any]]:
    kps = []
    for i, l in enumerate(lm):
        v = float(getattr(l, "visibility", 0.0) or 0.0)
        nx = (cl + float(l.x) * max(cw, 1)) / max(iw, 1)
        ny = (ct + float(l.y) * max(ch, 1)) / max(ih, 1)
        kps.append({"id": i, "name": LANDMARK_NAMES[i] if i < len(LANDMARK_NAMES) else f"landmark_{i}",
                     "x": float(nx), "y": float(ny), "z": float(l.z), "visibility": v if v >= 0.5 else 0.0})
    return kps


def _score_candidate(bbox: dict[str, float] | None, vs: float, prev: dict[str, float] | None, mot: dict[str, float] | None) -> float:
    if not bbox:
        return -1.0
    iou = _bbox_iou(prev, bbox)
    mo = _bbox_iou(mot, bbox)
    cx, cy = _bbox_center(bbox)
    px, py = _bbox_center(prev if prev else mot)
    cont = max(0.0, 1.0 - (abs(cx - px) + abs(cy - py)) * 2.5)
    sd = abs(_bbox_area(bbox) - _bbox_area(prev or mot)) if (prev or mot) else 0.0
    sc = max(0.0, 1.0 - sd * 6.0)
    vs2 = min(1.0, vs / 20.0)
    return round(iou * 0.34 + cont * 0.22 + sc * 0.14 + vs2 * 0.14 + mo * 0.16, 4)


def _resolve_tasks(root: Path | None = None) -> Any | None:
    np, mp = _pose_config()
    if not mp:
        return None
    rp = _resolve_model(mp, root)
    if rp is None or not rp.exists():
        return None
    try:
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        opts = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(rp)),
            num_poses=np, min_pose_detection_confidence=0.35,
            min_pose_presence_confidence=0.35, min_tracking_confidence=0.35, output_segmentation_masks=False,
        )
        return vision.PoseLandmarker.create_from_options(opts)
    except Exception:
        logger.warning("pose mode = fallback_single_pose (multi-pose init failed)", exc_info=True)
        return None


def extract_pose(frames_dir: str, target_lock: dict[str, Any] | None = None, project_root: Path | None = None) -> dict[str, Any]:
    np, _ = _pose_config()
    fps = sorted(Path(frames_dir).glob("frame_*.jpg"))
    if not fps:
        return _empty()
    try:
        import cv2
        import mediapipe as mp
    except Exception:
        return _empty()

    frames: list[dict[str, Any]] = []
    seed = extract_pose_target_bbox(target_lock)
    mot = (target_lock.get("selected_bbox") if isinstance(target_lock, dict) else None) or None
    prev = seed
    lost = 0
    tl = _resolve_tasks(project_root)
    sp = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1, enable_segmentation=False, min_detection_confidence=0.5)

    try:
        for fp in fps:
            img = cv2.imread(str(fp))
            if img is None:
                frames.append({"frame": fp.name, "keypoints": [], "target_bbox": prev, "tracking_confidence": 0.0, "tracking_state": "lost"})
                continue
            ih, iw = img.shape[:2]
            cands: list[dict[str, Any]] = []
            if tl is not None:
                try:
                    mi = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                    dr = tl.detect(mi)
                    for lm in dr.pose_landmarks:
                        bb = _bbox_from_landmarks(lm)
                        if not bb:
                            continue
                        cands.append({"bbox": bb, "visibility_sum": _vis_sum(lm),
                                      "keypoints": _map_kps(lm, 0, 0, iw, ih, iw, ih), "source": "tasks_multi_pose"})
                except Exception:
                    cands = []
            if not cands:
                l, t, r, b = _crop_bounds(iw, ih, seed or prev)
                cr = img[t:b, l:r]
                if cr.size > 0:
                    res = sp.process(cv2.cvtColor(cr, cv2.COLOR_BGR2RGB))
                    if res.pose_landmarks:
                        bb = seed or prev or {"x": round(l / max(iw, 1), 4), "y": round(t / max(ih, 1), 4),
                                              "width": round((r - l) / max(iw, 1), 4), "height": round((b - t) / max(ih, 1), 4)}
                        cands.append({"bbox": bb, "visibility_sum": _vis_sum(res.pose_landmarks.landmark),
                                      "keypoints": _map_kps(res.pose_landmarks.landmark, l, t, max(r - l, 1), max(b - t, 1), iw, ih),
                                      "source": "single_pose_crop"})
            scored = [{**c, "score": _score_candidate(c.get("bbox"), float(c.get("visibility_sum", 0.0)), prev, mot)} for c in cands]
            scored.sort(key=lambda x: float(x.get("score", -1.0)), reverse=True)
            best = scored[0] if scored and float(scored[0].get("score", -1.0)) >= 0.15 else None
            if best is None:
                lost += 1
                frames.append({"frame": fp.name, "keypoints": [], "target_bbox": prev, "tracking_confidence": 0.0,
                               "tracking_state": "lost" if lost > 0 else "missing",
                               "pose_candidates": [{"bbox": c.get("bbox"), "score": c.get("score"), "source": c.get("source")} for c in scored]})
                continue
            prev = best.get("bbox")
            lost = 0
            frames.append({"frame": fp.name, "keypoints": best.get("keypoints", []), "target_bbox": prev,
                           "tracking_confidence": round(float(best.get("score", 0.0)), 4), "tracking_state": "tracked",
                           "pose_candidates": [{"bbox": c.get("bbox"), "score": round(float(c.get("score", 0.0)), 4),
                                                "source": c.get("source")} for c in scored[:np]]})
    finally:
        sp.close()
        if tl is not None:
            tl.close()
    return {"connections": POSE_CONNECTIONS, "frames": frames}
