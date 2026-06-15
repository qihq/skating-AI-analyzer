from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


DEFAULT_OUTPUT_DIR = Path("tmp") / "target-preview-review"
BOX_COLORS = [
    (34, 197, 94),
    (59, 130, 246),
    (234, 179, 8),
    (239, 68, 68),
    (168, 85, 247),
    (20, 184, 166),
]
BACKGROUND_AUTO_LOCK_ALLOWED_FLAGS = {
    "target_lock_zoomed_multiperson_background_auto_lock_allowed",
    "target_lock_zoomed_multiperson_foreground_background_auto_lock_allowed",
    "target_lock_zoomed_multiperson_foreground_transient_background_auto_lock_allowed",
}
RISK_PRIORITY = {
    "same_anchor_competitor": 100,
    "selected_pair_competitor": 90,
    "high_competitor_load": 80,
    "foreground_deprioritized_alternative": 70,
    "foreground_context_small_target": 60,
    "zoomed_multiperson": 50,
    "compact_motion_reselected": 40,
}


def _risk_score(tags: list[Any]) -> int:
    return sum(RISK_PRIORITY.get(str(tag), 10) for tag in tags)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_timestamp(value: Any) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _pipeline_version_tuple(value: Any) -> tuple[int, int, int]:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _status_rank(item: dict[str, Any]) -> int:
    status = str(item.get("status") or "")
    if status == "completed":
        return 3
    if status == "awaiting_target_selection":
        return 2
    if status:
        return 1
    return 0


def _item_recency_key(item: dict[str, Any]) -> tuple[float, tuple[int, int, int], int, int, int]:
    timestamp = _parse_timestamp(item.get("updated_at"))
    if timestamp is None:
        timestamp = _parse_timestamp(item.get("created_at"))
    return (
        timestamp if timestamp is not None else -1.0,
        _pipeline_version_tuple(item.get("pipeline_version")),
        _status_rank(item),
        int(_safe_float(item.get("_source_index")) or 0),
        int(_safe_float(item.get("_source_row_index")) or 0),
    )


def _get_json(base_url: str, path: str, *, timeout: float) -> dict[str, Any]:
    request = Request(f"{base_url.rstrip('/')}{path}", headers={"X-Parent-Request": "true"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_bytes(base_url: str, path: str, *, timeout: float) -> bytes:
    request = Request(f"{base_url.rstrip('/')}{path}", headers={"X-Parent-Request": "true"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _batch_items(paths: list[Path]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for source_index, path in enumerate(paths):
        payload = _read_json(path)
        if isinstance(payload.get("unique_by_video_rows"), list):
            source_items = payload["unique_by_video_rows"]
        elif isinstance(payload.get("rows"), list):
            source_items = payload["rows"]
        elif isinstance(payload.get("videos"), list):
            source_items = payload["videos"]
        else:
            source_items = []
        for source_row_index, item in enumerate(source_items):
            if not isinstance(item, dict):
                continue
            analysis_id = str(item.get("analysis_id") or "")
            video = str(item.get("video") or "")
            if not analysis_id and not video:
                continue
            dedupe_key = (analysis_id, video)
            merged = dict(item)
            merged["_batch_file"] = path.name
            merged["_source_index"] = source_index
            merged["_source_row_index"] = source_row_index
            previous = deduped.get(dedupe_key)
            if previous is None or _item_recency_key(merged) >= _item_recency_key(previous):
                deduped[dedupe_key] = merged
    return list(deduped.values())


def _latest_items_by_video(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    no_video_items: list[dict[str, Any]] = []
    for item in items:
        video = str(item.get("video") or Path(str(item.get("video_path") or "")).name).strip()
        if not video:
            no_video_items.append(item)
            continue
        previous = latest.get(video)
        if previous is None or _item_recency_key(item) >= _item_recency_key(previous):
            latest[video] = item
    return [*latest.values(), *no_video_items]


def _matches_only_filters(item: dict[str, Any], filters: set[str]) -> bool:
    if not filters:
        return True
    values = {
        str(item.get("video") or "").lower(),
        Path(str(item.get("video") or "")).name.lower(),
        Path(str(item.get("video_path") or "")).name.lower(),
        str(item.get("analysis_id") or "").lower(),
    }
    stem_values = {Path(value).stem.lower() for value in values if value}
    return bool(values.intersection(filters) or stem_values.intersection(filters))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bbox_area(bbox: Any) -> float:
    if not isinstance(bbox, dict):
        return 0.0
    return max(0.0, _safe_float(bbox.get("width"))) * max(0.0, _safe_float(bbox.get("height")))


def _candidate_rank(candidate: dict[str, Any], auto_candidate_id: str | None) -> tuple[int, float, float, int]:
    flags = candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else []
    manual_review = any("_manual_review" in str(flag) for flag in flags)
    return (
        1 if str(candidate.get("id") or "") == str(auto_candidate_id or "") else 0,
        _safe_float(candidate.get("confidence")),
        _bbox_area(candidate.get("bbox")),
        0 if manual_review else 1,
    )


def _top_candidates(preview: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    candidates = [item for item in preview.get("candidates", []) if isinstance(item, dict)]
    auto_candidate_id = str(preview.get("auto_candidate_id") or "")
    candidates.sort(key=lambda item: _candidate_rank(item, auto_candidate_id), reverse=True)
    return candidates[:limit]


def _candidate_label(index: int, candidate: dict[str, Any], auto_candidate_id: str | None) -> str:
    prefix = f"C{index}"
    if str(candidate.get("id") or "") == str(auto_candidate_id or ""):
        prefix += "*"
    confidence = _safe_float(candidate.get("confidence"))
    return f"{prefix} {confidence:.2f}"


def _draw_candidate_boxes(image: Image.Image, preview: dict[str, Any], *, candidate_limit: int) -> Image.Image:
    rendered = image.convert("RGB").copy()
    draw = ImageDraw.Draw(rendered)
    width, height = rendered.size
    font = ImageFont.load_default()
    auto_candidate_id = str(preview.get("auto_candidate_id") or "")
    for index, candidate in enumerate(_top_candidates(preview, candidate_limit), start=1):
        bbox = candidate.get("bbox")
        if not isinstance(bbox, dict):
            continue
        x1 = int(_safe_float(bbox.get("x")) * width)
        y1 = int(_safe_float(bbox.get("y")) * height)
        x2 = int((_safe_float(bbox.get("x")) + _safe_float(bbox.get("width"))) * width)
        y2 = int((_safe_float(bbox.get("y")) + _safe_float(bbox.get("height"))) * height)
        color = BOX_COLORS[(index - 1) % len(BOX_COLORS)]
        line_width = 4 if str(candidate.get("id") or "") == auto_candidate_id else 2
        draw.rectangle((x1, y1, x2, y2), outline=color, width=line_width)
        label = _candidate_label(index, candidate, auto_candidate_id)
        label_bbox = draw.textbbox((x1, max(0, y1 - 14)), label, font=font)
        draw.rectangle(label_bbox, fill=color)
        draw.text((x1, max(0, y1 - 14)), label, fill=(0, 0, 0), font=font)
    return rendered


def _bbox_pixel_rect(
    bbox: Any,
    *,
    image_width: int,
    image_height: int,
    padding_ratio: float = 0.18,
) -> tuple[int, int, int, int] | None:
    if not isinstance(bbox, dict):
        return None
    x = _safe_float(bbox.get("x"))
    y = _safe_float(bbox.get("y"))
    width = _safe_float(bbox.get("width"))
    height = _safe_float(bbox.get("height"))
    if width <= 0 or height <= 0 or image_width <= 0 or image_height <= 0:
        return None

    pad_x = width * image_width * padding_ratio
    pad_y = height * image_height * padding_ratio
    x1 = max(0, int(round(x * image_width - pad_x)))
    y1 = max(0, int(round(y * image_height - pad_y)))
    x2 = min(image_width, int(round((x + width) * image_width + pad_x)))
    y2 = min(image_height, int(round((y + height) * image_height + pad_y)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _candidate_crop_filename(video_or_analysis: Any, index: int, candidate: dict[str, Any]) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(str(video_or_analysis or "analysis")).stem).strip("._")
    if not stem:
        stem = "analysis"
    candidate_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(candidate.get("id") or f"candidate_{index}")).strip("._")
    if not candidate_id:
        candidate_id = f"candidate_{index}"
    return f"{stem}_C{index}_{candidate_id[:24]}.jpg"


def _candidate_anchor_frame(candidate: dict[str, Any]) -> str:
    frame = str(candidate.get("anchor_frame") or "").strip()
    return frame if frame else ""


def _load_candidate_anchor_images(
    *,
    base_url: str,
    analysis_id: str,
    preview: dict[str, Any],
    candidates: list[dict[str, Any]],
    frames_root: Path | None,
    timeout: float,
) -> dict[str, Image.Image]:
    preview_frame = str(preview.get("preview_frame") or "")
    frame_names = sorted(
        {
            _candidate_anchor_frame(candidate)
            for candidate in candidates
            if _candidate_anchor_frame(candidate) and _candidate_anchor_frame(candidate) != preview_frame
        }
    )
    images: dict[str, Image.Image] = {}
    for frame_name in frame_names:
        try:
            image = _open_preview_image(
                base_url=base_url,
                analysis_id=analysis_id,
                frame_name=frame_name,
                frame_url=f"/api/frames/{analysis_id}/{frame_name}",
                frames_root=frames_root,
                timeout=timeout,
            )
        except Exception:  # noqa: BLE001
            image = None
        if image is not None:
            images[frame_name] = image
    return images


def _save_candidate_crops(
    image: Image.Image,
    preview: dict[str, Any],
    *,
    crop_dir: Path,
    video_or_analysis: Any,
    candidate_limit: int,
    anchor_images: dict[str, Image.Image] | None = None,
) -> dict[str, dict[str, Any]]:
    crop_dir.mkdir(parents=True, exist_ok=True)
    preview_rgb = image.convert("RGB")
    preview_frame = str(preview.get("preview_frame") or "")
    paths: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(_top_candidates(preview, candidate_limit), start=1):
        candidate_id = str(candidate.get("id") or "")
        anchor_frame = _candidate_anchor_frame(candidate)
        source = (anchor_images or {}).get(anchor_frame) if anchor_frame else None
        source_frame = anchor_frame if source is not None else preview_frame
        rgb = (source or preview_rgb).convert("RGB")
        rect = _bbox_pixel_rect(candidate.get("bbox"), image_width=rgb.width, image_height=rgb.height)
        if not candidate_id or rect is None:
            continue
        crop = rgb.crop(rect)
        crop.thumbnail((260, 260))
        crop_path = crop_dir / _candidate_crop_filename(video_or_analysis, index, candidate)
        crop.save(crop_path, quality=92)
        paths[candidate_id] = {"path": crop_path, "source_frame": source_frame or None}
    return paths


def _open_image_from_api(base_url: str, frame_url: str | None, *, timeout: float) -> Image.Image | None:
    if not frame_url:
        return None
    data = _get_bytes(base_url, frame_url, timeout=timeout)
    from io import BytesIO

    return Image.open(BytesIO(data))


def _open_image_from_frames_root(frames_root: Path | None, analysis_id: str, frame_name: str | None) -> Image.Image | None:
    if frames_root is None or not frame_name:
        return None
    path = frames_root / analysis_id / "frames" / str(frame_name)
    if not path.exists():
        return None
    with Image.open(path) as image:
        return image.copy()


def _open_preview_image(
    *,
    base_url: str,
    analysis_id: str,
    frame_name: str | None,
    frame_url: str | None,
    frames_root: Path | None,
    timeout: float,
) -> Image.Image | None:
    image = _open_image_from_frames_root(frames_root, analysis_id, frame_name)
    if image is not None:
        return image
    return _open_image_from_api(base_url, frame_url, timeout=timeout)


def _candidate_summary(
    candidate: dict[str, Any],
    index: int,
    auto_candidate_id: str | None,
    *,
    crop_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    crop_path = crop_info.get("path") if isinstance(crop_info, dict) else None
    return {
        "label": f"C{index}" + ("*" if str(candidate.get("id") or "") == str(auto_candidate_id or "") else ""),
        "id": candidate.get("id"),
        "confidence": candidate.get("confidence"),
        "source": candidate.get("source"),
        "bbox": candidate.get("bbox"),
        "crop_image": str(crop_path) if crop_path else None,
        "crop_source_frame": crop_info.get("source_frame") if isinstance(crop_info, dict) else None,
        "support_count": candidate.get("support_count"),
        "support_frame_count": candidate.get("support_frame_count"),
        "support_confidence": candidate.get("support_confidence"),
        "anchor_frame": candidate.get("anchor_frame"),
        "anchor_index": candidate.get("anchor_index"),
        "support_anchor_frames": candidate.get("support_anchor_frames") if isinstance(candidate.get("support_anchor_frames"), list) else [],
        "support_center_span": candidate.get("support_center_span"),
        "support_avg_area": candidate.get("support_avg_area"),
        "support_motion_anchor_hits": candidate.get("support_motion_anchor_hits"),
        "multiperson_ambiguous_frame_count": candidate.get("multiperson_ambiguous_frame_count"),
        "multiperson_competitor_count": candidate.get("multiperson_competitor_count"),
        "multiperson_same_anchor_competitor_count": candidate.get("multiperson_same_anchor_competitor_count"),
        "multiperson_selected_pair_frame_count": candidate.get("multiperson_selected_pair_frame_count"),
        "multiperson_selected_pair_competitor_count": candidate.get("multiperson_selected_pair_competitor_count"),
        "multiperson_other_frame_ambiguous_count": candidate.get("multiperson_other_frame_ambiguous_count"),
        "multiperson_nearest_center_distance": candidate.get("multiperson_nearest_center_distance"),
        "multiperson_max_competitor_confidence": candidate.get("multiperson_max_competitor_confidence"),
        "multiperson_ignored_fragment_count": candidate.get("multiperson_ignored_fragment_count"),
        "quality_flags": candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else [],
    }


def _review_risk_tags(preview: dict[str, Any], candidates: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    first = candidates[0] if candidates else {}
    flags = first.get("quality_flags") if isinstance(first.get("quality_flags"), list) else []
    if "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk" in flags:
        tags.append("compact_motion_reselected")
    if "target_lock_foreground_context_small_target_manual_review" in flags:
        tags.append("foreground_context_small_target")
    if "target_lock_zoomed_multiperson_manual_review" in flags:
        tags.append("zoomed_multiperson")
    if _safe_float(first.get("multiperson_selected_pair_frame_count")) > 0:
        tags.append("selected_pair_competitor")
    if _safe_float(first.get("multiperson_same_anchor_competitor_count")) > 0:
        tags.append("same_anchor_competitor")
    if _safe_float(first.get("multiperson_competitor_count")) >= 20:
        tags.append("high_competitor_load")
    for candidate in candidates[1:]:
        candidate_flags = candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else []
        if any(str(flag).startswith("target_lock_zoomed_foreground_deprioritized") for flag in candidate_flags):
            tags.append("foreground_deprioritized_alternative")
            break
    return list(dict.fromkeys(tags))


def _review_row(
    item: dict[str, Any],
    preview: dict[str, Any],
    *,
    image_path: Path | None,
    candidate_limit: int,
    candidate_crop_paths: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    auto_candidate_id = str(preview.get("auto_candidate_id") or "")
    candidates = _top_candidates(preview, candidate_limit)
    candidate_summaries = [
        _candidate_summary(
            candidate,
            index,
            auto_candidate_id,
            crop_info=(candidate_crop_paths or {}).get(str(candidate.get("id") or "")),
        )
        for index, candidate in enumerate(candidates, start=1)
    ]
    return {
        "video": item.get("video"),
        "analysis_id": item.get("analysis_id"),
        "batch_file": item.get("_batch_file"),
        "status": item.get("status"),
        "target_lock_status": preview.get("target_lock_status"),
        "auto_candidate_id": auto_candidate_id or None,
        "preview_frame": preview.get("preview_frame"),
        "preview_frame_url": preview.get("preview_frame_url"),
        "overlay_image": str(image_path) if image_path else None,
        "review_risk_tags": _review_risk_tags(preview, candidate_summaries),
        "candidates": candidate_summaries,
    }


def _review_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    risk_tags: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    auto_rank_counts: Counter[str] = Counter()
    top_candidate_flags: Counter[str] = Counter()
    allowed_with_manual_review = 0
    for row in rows:
        risk_tags.update(str(tag) for tag in row.get("review_risk_tags", []) if str(tag).strip())
        status_counts.update([str(row.get("target_lock_status") or "unknown")])
        candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else []
        candidate_counts.update([str(len(candidates))])
        auto_candidate_id = str(row.get("auto_candidate_id") or "")
        for index, candidate in enumerate(candidates, start=1):
            if str(candidate.get("id") or "") == auto_candidate_id:
                auto_rank_counts.update([str(index)])
                break
        top = candidates[0] if candidates else {}
        flags = [str(flag) for flag in top.get("quality_flags", []) if str(flag).strip()]
        top_candidate_flags.update(flags)
        if (
            any(flag in BACKGROUND_AUTO_LOCK_ALLOWED_FLAGS for flag in flags)
            and (
                str(row.get("target_lock_status") or "") != "auto_locked"
                or any("_manual_review" in flag for flag in flags)
                or "target_lock_auto_lock_blocked_by_manual_review" in flags
            )
        ):
            allowed_with_manual_review += 1
    return {
        "risk_tag_counts": dict(risk_tags.most_common()),
        "target_lock_status_counts": dict(status_counts.most_common()),
        "candidate_count_distribution": dict(candidate_counts.most_common()),
        "auto_candidate_rank_counts": dict(auto_rank_counts.most_common()),
        "top_candidate_flag_counts": dict(top_candidate_flags.most_common(30)),
        "background_auto_lock_allowed_with_manual_review_count": allowed_with_manual_review,
    }


def _write_contact_sheet(rows: list[dict[str, Any]], output_path: Path, *, thumb_width: int = 420) -> None:
    images: list[tuple[dict[str, Any], Image.Image]] = []
    for row in rows:
        image_path = row.get("overlay_image")
        if not image_path:
            continue
        path = Path(str(image_path))
        if not path.exists():
            continue
        image = Image.open(path).convert("RGB")
        ratio = thumb_width / max(image.width, 1)
        thumb = image.resize((thumb_width, max(1, int(image.height * ratio))))
        images.append((row, thumb))
    if not images:
        return

    padding = 18
    label_height = 62
    columns = 2
    cell_width = thumb_width + padding * 2
    cell_height = max(image.height for _, image in images) + label_height + padding * 2
    rows_count = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows_count), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for idx, (row, image) in enumerate(images):
        col = idx % columns
        grid_row = idx // columns
        x = col * cell_width + padding
        y = grid_row * cell_height + padding
        sheet.paste(image, (x, y + label_height))
        title = str(row.get("video") or "")[:60]
        target = f"auto={row.get('auto_candidate_id')} status={row.get('target_lock_status')}"
        draw.text((x, y), title, fill=(0, 0, 0), font=font)
        draw.text((x, y + 16), target[:70], fill=(0, 0, 0), font=font)
        first = row.get("candidates", [{}])[0] if isinstance(row.get("candidates"), list) and row.get("candidates") else {}
        ambiguity = (
            f"ambig_frames={first.get('multiperson_ambiguous_frame_count')} "
            f"selected_pair={first.get('multiperson_selected_pair_frame_count')} "
            f"competitors={first.get('multiperson_competitor_count')} "
            f"max_conf={first.get('multiperson_max_competitor_confidence')}"
        )
        draw.text((x, y + 32), ambiguity[:70], fill=(0, 0, 0), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def _write_markdown(rows: list[dict[str, Any]], output_path: Path, *, label: str, template_path: Path) -> None:
    summary = _review_summary(rows)
    lines = [
        "# Target Preview Review",
        "",
        f"- Label: {label}",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Rows: {len(rows)}",
        f"- Selection template: {template_path}",
        "",
        "## Summary",
        "",
        f"- Target status counts: {json.dumps(summary['target_lock_status_counts'], ensure_ascii=False, sort_keys=True)}",
        f"- Risk tag counts: {json.dumps(summary['risk_tag_counts'], ensure_ascii=False, sort_keys=True)}",
        f"- Candidate count distribution: {json.dumps(summary['candidate_count_distribution'], ensure_ascii=False, sort_keys=True)}",
        f"- Auto candidate rank counts: {json.dumps(summary['auto_candidate_rank_counts'], ensure_ascii=False, sort_keys=True)}",
        f"- Background auto-lock allowed with manual-review count: {summary['background_auto_lock_allowed_with_manual_review_count']}",
        "",
        "## Rows",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row.get('video')}",
                "",
                f"- Analysis: {row.get('analysis_id')}",
                f"- Status: {row.get('target_lock_status')}",
                f"- Auto candidate: {row.get('auto_candidate_id')}",
                f"- Risk tags: {', '.join(str(tag) for tag in row.get('review_risk_tags', []))}",
                f"- Overlay: {row.get('overlay_image')}",
                "",
                "| Label | Candidate ID | Conf | Crop | Anchor | Support | Multi-person | Flags |",
                "| --- | --- | ---: | --- | --- | --- | --- | --- |",
            ]
        )
        for candidate in row.get("candidates", []) if isinstance(row.get("candidates"), list) else []:
            flags = ", ".join(str(flag) for flag in candidate.get("quality_flags", []))
            support = f"{candidate.get('support_count')}/{candidate.get('support_frame_count')} span={candidate.get('support_center_span')}"
            multi = (
                f"frames={candidate.get('multiperson_ambiguous_frame_count')} "
                f"selected_pair={candidate.get('multiperson_selected_pair_frame_count')} "
                f"other={candidate.get('multiperson_other_frame_ambiguous_count')} "
                f"comp={candidate.get('multiperson_competitor_count')} "
                f"max={candidate.get('multiperson_max_competitor_confidence')}"
            )
            lines.append(
                f"| {candidate.get('label')} | `{candidate.get('id')}` | {candidate.get('confidence')} | {candidate.get('crop_image')} | {candidate.get('anchor_frame')} | {support} | {multi} | {flags} |"
            )
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _relative_html_path(path: str | None, *, base_dir: Path) -> str:
    if not path:
        return ""
    candidate = Path(str(path))
    try:
        rel = candidate.relative_to(base_dir)
    except ValueError:
        try:
            rel = candidate.resolve().relative_to(base_dir.resolve())
        except (OSError, ValueError):
            rel = candidate
    return rel.as_posix()


def _target_review_url(frontend_url: str, analysis_id: Any) -> str:
    analysis = str(analysis_id or "").strip()
    if not analysis:
        return ""
    return f"{frontend_url.rstrip('/')}/report/{analysis}/target"


def _write_html_index(
    rows: list[dict[str, Any]],
    output_path: Path,
    *,
    label: str,
    frontend_url: str,
    template_path: Path,
    review_json_path: Path,
    review_md_path: Path,
) -> None:
    output_dir = output_path.parent
    summary = _review_summary(rows)
    style = """
body { margin: 0; font-family: Arial, sans-serif; color: #172033; background: #f7f8fb; }
main { max-width: 1180px; margin: 0 auto; padding: 24px; }
h1 { margin: 0 0 8px; font-size: 28px; }
.meta { color: #536076; line-height: 1.55; }
.links { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 24px; }
.links a, .open-link, button { border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; color: #0f4b99; background: white; text-decoration: none; font-weight: 700; cursor: pointer; }
.review-toolbar { position: sticky; top: 0; z-index: 2; border: 1px solid #d8dee9; border-radius: 8px; background: #ffffff; padding: 12px; margin: 0 0 18px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); }
.review-toolbar .actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
.selected-count { color: #334155; font-weight: 800; }
.missing-count { color: #b45309; font-weight: 800; }
.completion-status { border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 800; background: #fef3c7; color: #92400e; }
.completion-status.complete { background: #dcfce7; color: #166534; }
.completion-status.incomplete { background: #fee2e2; color: #991b1b; }
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
.filters input[type="search"], .filters select { border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; min-height: 36px; }
.filters input[type="search"] { flex: 1 1 260px; }
.filters label { display: inline-flex; gap: 6px; align-items: center; color: #334155; font-size: 13px; font-weight: 700; }
.visible-count { color: #64748b; font-weight: 800; }
.selection-output { box-sizing: border-box; width: 100%; min-height: 150px; resize: vertical; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; font-family: Consolas, monospace; font-size: 12px; color: #172033; background: #f8fafc; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin: 0 0 18px; }
.summary div { border: 1px solid #d8dee9; border-radius: 8px; background: white; padding: 10px; }
.summary strong { display: block; margin-bottom: 4px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(390px, 1fr)); gap: 16px; }
article { border: 1px solid #d8dee9; border-radius: 8px; background: white; overflow: hidden; }
article[hidden] { display: none; }
article:focus-within { outline: 3px solid #93c5fd; outline-offset: 2px; }
article[data-selected="true"] { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.18); }
article img { display: block; width: 100%; background: #111827; }
.content { padding: 14px; }
.video { font-weight: 800; overflow-wrap: anywhere; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.tag { border-radius: 999px; background: #eef2ff; color: #334155; padding: 4px 8px; font-size: 12px; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
th, td { border-top: 1px solid #e5e7eb; padding: 6px; text-align: left; vertical-align: top; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: #f8fafc; }
tbody tr:has(input:checked) { background: #eff6ff; }
.choice { width: 34px; text-align: center; }
.choice input { width: 18px; height: 18px; cursor: pointer; }
.crop { width: 104px; }
.crop img { width: 96px; height: 96px; object-fit: cover; border-radius: 4px; background: #111827; }
code { background: #f1f5f9; border-radius: 4px; padding: 2px 4px; overflow-wrap: anywhere; }
""".strip()
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(label)} Target Review</title>",
        f"<style>{style}</style>",
        "</head>",
        "<body>",
        "<main>",
        "<h1>Target Preview Review</h1>",
        f'<div class="meta">Label: {html.escape(label)}<br>Rows: {len(rows)}<br>Generated: {html.escape(datetime.now().isoformat(timespec="seconds"))}</div>',
        '<div class="links">',
        f'<a href="{html.escape(_relative_html_path(str(template_path), base_dir=output_dir))}">Selection template JSON</a>',
        f'<a href="{html.escape(_relative_html_path(str(review_json_path), base_dir=output_dir))}">Review JSON</a>',
        f'<a href="{html.escape(_relative_html_path(str(review_md_path), base_dir=output_dir))}">Markdown report</a>',
        "</div>",
        '<section class="review-toolbar">',
        '<div class="actions">',
        f'<span class="selected-count" id="selectedCount">Selected: 0 / {len(rows)}</span>',
        f'<span class="missing-count" id="missingCount">Missing: {len(rows)}</span>',
        '<span class="completion-status incomplete" id="completionStatus">Needs review</span>',
        '<button type="button" id="copySelection">Copy JSON</button>',
        '<button type="button" id="downloadSelection">Download JSON</button>',
        '<button type="button" id="prevUnselected">Prev Unselected</button>',
        '<button type="button" id="nextUnselected">Next Unselected</button>',
        '<button type="button" id="clearSelection">Clear</button>',
        "</div>",
        '<div class="filters">',
        '<input type="search" id="reviewSearch" placeholder="Search video or candidate ID">',
        '<select id="riskFilter" aria-label="Risk filter">',
        '<option value="">All risks</option>',
        *[
            f'<option value="{html.escape(str(tag), quote=True)}">{html.escape(str(tag))} ({count})</option>'
            for tag, count in summary["risk_tag_counts"].items()
        ],
        "</select>",
        '<select id="sortMode" aria-label="Sort mode">',
        '<option value="risk">Risk first</option>',
        '<option value="original">Original order</option>',
        '<option value="video">Video name</option>',
        "</select>",
        '<label><input type="checkbox" id="showUnselectedOnly"> Unselected only</label>',
        '<span class="visible-count" id="visibleCount">Visible: 0</span>',
        "</div>",
        '<textarea class="selection-output" id="selectionOutput" spellcheck="false" aria-label="Target selection JSON"></textarea>',
        "</section>",
        '<section class="summary">',
        f"<div><strong>Status</strong>{html.escape(json.dumps(summary['target_lock_status_counts'], ensure_ascii=False, sort_keys=True))}</div>",
        f"<div><strong>Risk Tags</strong>{html.escape(json.dumps(summary['risk_tag_counts'], ensure_ascii=False, sort_keys=True))}</div>",
        f"<div><strong>Candidate Counts</strong>{html.escape(json.dumps(summary['candidate_count_distribution'], ensure_ascii=False, sort_keys=True))}</div>",
        f"<div><strong>Allowed+Manual</strong>{summary['background_auto_lock_allowed_with_manual_review_count']}</div>",
        "</section>",
        '<section class="grid">',
    ]
    for row_index, row in enumerate(rows):
        overlay = _relative_html_path(row.get("overlay_image"), base_dir=output_dir)
        target_url = _target_review_url(frontend_url, row.get("analysis_id"))
        tags = row.get("review_risk_tags") if isinstance(row.get("review_risk_tags"), list) else []
        risk_score = _risk_score(tags)
        video_name = str(row.get("video") or "")
        analysis_id = str(row.get("analysis_id") or "")
        auto_candidate_id = str(row.get("auto_candidate_id") or "")
        lines.extend(
            [
                f'<article id="row-{row_index}" data-video="{html.escape(video_name.lower(), quote=True)}" data-video-name="{html.escape(video_name, quote=True)}" data-tags="{html.escape(" ".join(str(tag).lower() for tag in tags), quote=True)}" data-risk-score="{risk_score}" data-original-index="{row_index}" data-selected="false">',
                f'<img src="{html.escape(overlay)}" alt="{html.escape(video_name or "target preview")}">',
                '<div class="content">',
                f'<div class="video">{html.escape(video_name)}</div>',
                f'<div class="meta">Analysis: <code>{html.escape(analysis_id)}</code><br>Status: {html.escape(str(row.get("target_lock_status") or ""))}<br>Auto: <code>{html.escape(auto_candidate_id)}</code></div>',
                '<div class="tags">' + "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in tags) + "</div>",
            ]
        )
        if target_url:
            lines.append(f'<a class="open-link" href="{html.escape(target_url)}" target="_blank" rel="noopener">Open target selection</a>')
        lines.extend(
            [
                "<table>",
                "<thead><tr><th class=\"choice\">Use</th><th class=\"crop\">Crop</th><th>Label</th><th>Candidate ID</th><th>Conf</th><th>Anchor</th><th>Multi-person</th></tr></thead>",
                "<tbody>",
            ]
        )
        for candidate_index, candidate in enumerate(row.get("candidates", []) if isinstance(row.get("candidates"), list) else []):
            candidate_id = str(candidate.get("id") or "")
            candidate_label = str(candidate.get("label") or "")
            crop = _relative_html_path(candidate.get("crop_image"), base_dir=output_dir)
            crop_html = (
                f'<img src="{html.escape(crop)}" alt="{html.escape(candidate_label or candidate_id)} crop">'
                if crop
                else ""
            )
            anchor = str(candidate.get("anchor_frame") or "")
            crop_source = str(candidate.get("crop_source_frame") or "")
            multi = (
                f"frames={candidate.get('multiperson_ambiguous_frame_count')} "
                f"pair={candidate.get('multiperson_selected_pair_frame_count')} "
                f"comp={candidate.get('multiperson_competitor_count')} "
                f"max={candidate.get('multiperson_max_competitor_confidence')}"
            )
            lines.append(
                "<tr>"
                f'<td class="choice"><input type="radio" name="target-{row_index}" value="{html.escape(candidate_id, quote=True)}" data-video="{html.escape(video_name, quote=True)}" data-analysis-id="{html.escape(analysis_id, quote=True)}" data-label="{html.escape(candidate_label, quote=True)}" data-auto-candidate-id="{html.escape(auto_candidate_id, quote=True)}" data-index="{candidate_index + 1}"></td>'
                f'<td class="crop">{crop_html}</td>'
                f"<td>{html.escape(candidate_label)}</td>"
                f"<td><code>{html.escape(candidate_id)}</code></td>"
                f"<td>{html.escape(str(candidate.get('confidence') or ''))}</td>"
                f"<td>{html.escape(anchor)}<br><span class=\"meta\">crop: {html.escape(crop_source)}</span></td>"
                f"<td>{html.escape(multi)}</td>"
                "</tr>"
            )
        lines.extend(["</tbody>", "</table>", "</div>", "</article>"])
    script = f"""
<script>
(function() {{
  const storageKey = "target-review-selection:{html.escape(label, quote=True)}";
  const output = document.getElementById("selectionOutput");
  const selectedCount = document.getElementById("selectedCount");
  const missingCount = document.getElementById("missingCount");
  const completionStatus = document.getElementById("completionStatus");
  const visibleCount = document.getElementById("visibleCount");
  const searchInput = document.getElementById("reviewSearch");
  const riskFilter = document.getElementById("riskFilter");
  const sortMode = document.getElementById("sortMode");
  const showUnselectedOnly = document.getElementById("showUnselectedOnly");
  const radios = Array.from(document.querySelectorAll("input[type=radio][data-video]"));
  const articles = Array.from(document.querySelectorAll("article[data-video]"));
  const grid = document.querySelector(".grid");
  const totalRows = articles.length;
  let activeArticle = articles[0] || null;
  function articleSortValue(article, mode) {{
    if (mode === "video") return (article.dataset.videoName || article.dataset.video || "").toLowerCase();
    if (mode === "original") return Number(article.dataset.originalIndex || 0);
    return -Number(article.dataset.riskScore || 0);
  }}
  function sortArticles() {{
    if (!grid) return;
    const mode = sortMode.value || "risk";
    const sorted = [...articles].sort((left, right) => {{
      const leftValue = articleSortValue(left, mode);
      const rightValue = articleSortValue(right, mode);
      if (leftValue < rightValue) return -1;
      if (leftValue > rightValue) return 1;
      return Number(left.dataset.originalIndex || 0) - Number(right.dataset.originalIndex || 0);
    }});
    for (const article of sorted) grid.appendChild(article);
    if (!activeArticle || activeArticle.hidden) {{
      activeArticle = sorted.find((article) => !article.hidden) || sorted[0] || null;
    }}
  }}
  function buildPayload() {{
    const videos = {{}};
    for (const input of radios) {{
      if (!input.checked) continue;
      videos[input.dataset.video] = {{
        candidate_id: input.value,
        _analysis_id: input.dataset.analysisId || "",
        _suggested_auto_candidate_id: input.dataset.autoCandidateId || "",
        _selected_label: input.dataset.label || "",
        _selected_rank: input.dataset.index || "",
        _source: "target-preview-review-html"
      }};
    }}
    const selected = Object.keys(videos).length;
    const missing = Math.max(totalRows - selected, 0);
    return {{
      _review_label: {json.dumps(label, ensure_ascii=False)},
      _review_row_count: totalRows,
      _selected_count: selected,
      _missing_count: missing,
      _complete: missing === 0,
      _source: "target-preview-review-html",
      videos
    }};
  }}
  function render() {{
    const payload = buildPayload();
    const count = payload._selected_count || 0;
    const missing = payload._missing_count || 0;
    selectedCount.textContent = `Selected: ${{count}} / ${{totalRows}}`;
    missingCount.textContent = `Missing: ${{missing}}`;
    completionStatus.textContent = payload._complete ? "Complete" : "Needs review";
    completionStatus.classList.toggle("complete", payload._complete);
    completionStatus.classList.toggle("incomplete", !payload._complete);
    output.value = JSON.stringify(payload, null, 2);
    localStorage.setItem(storageKey, JSON.stringify(payload.videos));
    for (const article of articles) {{
      const selected = Boolean(article.querySelector("input[type=radio]:checked"));
      article.dataset.selected = selected ? "true" : "false";
    }}
    applyFilters();
    sortArticles();
  }}
  function articleMatchesSearch(article, query) {{
    if (!query) return true;
    if ((article.dataset.video || "").includes(query)) return true;
    return Array.from(article.querySelectorAll("code")).some((item) => item.textContent.toLowerCase().includes(query));
  }}
  function applyFilters() {{
    const query = (searchInput.value || "").trim().toLowerCase();
    const risk = (riskFilter.value || "").trim().toLowerCase();
    const unselectedOnly = showUnselectedOnly.checked;
    let visible = 0;
    for (const article of articles) {{
      const matchesSearch = articleMatchesSearch(article, query);
      const matchesRisk = !risk || (article.dataset.tags || "").split(" ").includes(risk);
      const matchesSelected = !unselectedOnly || article.dataset.selected !== "true";
      const show = matchesSearch && matchesRisk && matchesSelected;
      article.hidden = !show;
      if (show) visible += 1;
    }}
    visibleCount.textContent = `Visible: ${{visible}}`;
    if (!activeArticle || activeArticle.hidden) {{
      activeArticle = articles.find((article) => !article.hidden) || null;
    }}
  }}
  function focusArticle(article) {{
    if (!article) return;
    activeArticle = article;
    const firstInput = article.querySelector("input[type=radio]");
    if (firstInput) firstInput.focus({{ preventScroll: true }});
    article.scrollIntoView({{ block: "center", behavior: "smooth" }});
  }}
  function visibleArticles() {{
    return articles.filter((article) => !article.hidden);
  }}
  function nearestVisibleIndex() {{
    const visible = visibleArticles();
    const index = visible.indexOf(activeArticle);
    return {{ visible, index: index >= 0 ? index : 0 }};
  }}
  function focusAdjacentUnselected(direction) {{
    const {{ visible, index }} = nearestVisibleIndex();
    if (!visible.length) return;
    for (let step = 1; step <= visible.length; step += 1) {{
      const next = visible[(index + direction * step + visible.length) % visible.length];
      if (next.dataset.selected !== "true") {{
        focusArticle(next);
        return;
      }}
    }}
    focusArticle(visible[index] || visible[0]);
  }}
  function chooseCandidateByNumber(numberText) {{
    if (!activeArticle || activeArticle.hidden) {{
      activeArticle = visibleArticles()[0] || null;
    }}
    if (!activeArticle) return;
    const input = activeArticle.querySelector(`input[type=radio][data-index="${{numberText}}"]`);
    if (!input) return;
    input.checked = true;
    input.dispatchEvent(new Event("change", {{ bubbles: true }}));
    focusAdjacentUnselected(1);
  }}
  function restore() {{
    let saved = {{}};
    try {{
      saved = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
    }} catch (error) {{
      saved = {{}};
    }}
    for (const input of radios) {{
      const item = saved[input.dataset.video];
      if (item && item.candidate_id === input.value) {{
        input.checked = true;
      }}
    }}
    render();
  }}
  async function copyOutput() {{
    render();
    output.focus();
    output.select();
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      await navigator.clipboard.writeText(output.value);
    }} else {{
      document.execCommand("copy");
    }}
  }}
  function downloadOutput() {{
    render();
    const blob = new Blob([output.value], {{ type: "application/json" }});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "target-selection-reviewed.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }}
  function clearSelection() {{
    for (const input of radios) input.checked = false;
    localStorage.removeItem(storageKey);
    render();
  }}
  for (const input of radios) input.addEventListener("change", render);
  for (const article of articles) {{
    article.addEventListener("focusin", () => {{
      activeArticle = article;
    }});
    article.addEventListener("click", (event) => {{
      activeArticle = article;
      const row = event.target.closest("tr");
      if (!row) return;
      const input = row.querySelector("input[type=radio]");
      if (!input) return;
      input.checked = true;
      input.dispatchEvent(new Event("change", {{ bubbles: true }}));
    }});
  }}
  document.addEventListener("keydown", (event) => {{
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const tagName = (event.target && event.target.tagName || "").toLowerCase();
    if (tagName === "input" || tagName === "textarea" || tagName === "select") return;
    if (/^[1-6]$/.test(event.key)) {{
      event.preventDefault();
      chooseCandidateByNumber(event.key);
    }} else if (event.key === "j" || event.key === "ArrowDown") {{
      event.preventDefault();
      focusAdjacentUnselected(1);
    }} else if (event.key === "k" || event.key === "ArrowUp") {{
      event.preventDefault();
      focusAdjacentUnselected(-1);
    }}
  }});
  searchInput.addEventListener("input", applyFilters);
  riskFilter.addEventListener("change", applyFilters);
  sortMode.addEventListener("change", () => {{
    sortArticles();
    applyFilters();
  }});
  showUnselectedOnly.addEventListener("change", applyFilters);
  document.getElementById("copySelection").addEventListener("click", copyOutput);
  document.getElementById("downloadSelection").addEventListener("click", downloadOutput);
  document.getElementById("prevUnselected").addEventListener("click", () => focusAdjacentUnselected(-1));
  document.getElementById("nextUnselected").addEventListener("click", () => focusAdjacentUnselected(1));
  document.getElementById("clearSelection").addEventListener("click", clearSelection);
  restore();
}})();
</script>
""".strip()
    lines.extend(["</section>", script, "</main>", "</body>", "</html>"])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_selection_template(rows: list[dict[str, Any]], output_path: Path) -> None:
    payload = {
        "videos": {
            str(row.get("video")): {
                "candidate_id": "",
                "_suggested_auto_candidate_id": row.get("auto_candidate_id"),
                "_analysis_id": row.get("analysis_id"),
                "_overlay_image": row.get("overlay_image"),
                "_note": "Fill candidate_id with a reviewed candidate, or replace with manual_bbox.",
            }
            for row in rows
            if row.get("video")
        }
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _export_one_review_row(
    item: dict[str, Any],
    *,
    base_url: str,
    overlay_dir: Path,
    frames_root: Path | None,
    timeout: float,
    candidate_limit: int,
) -> dict[str, Any]:
    analysis_id = str(item.get("analysis_id") or "")
    preview = _get_json(base_url, f"/api/analysis/{analysis_id}/target-preview", timeout=timeout)
    image = _open_preview_image(
        base_url=base_url,
        analysis_id=analysis_id,
        frame_name=preview.get("preview_frame"),
        frame_url=preview.get("preview_frame_url"),
        frames_root=frames_root,
        timeout=timeout,
    )
    image_path: Path | None = None
    candidate_crop_paths: dict[str, dict[str, Any]] = {}
    if image is not None:
        candidates = _top_candidates(preview, candidate_limit)
        anchor_images = _load_candidate_anchor_images(
            base_url=base_url,
            analysis_id=analysis_id,
            preview=preview,
            candidates=candidates,
            frames_root=frames_root,
            timeout=timeout,
        )
        rendered = _draw_candidate_boxes(image, preview, candidate_limit=candidate_limit)
        image_path = overlay_dir / f"{Path(str(item.get('video') or analysis_id)).stem}.jpg"
        rendered.save(image_path, quality=92)
        candidate_crop_paths = _save_candidate_crops(
            image,
            preview,
            crop_dir=overlay_dir / "crops",
            video_or_analysis=item.get("video") or analysis_id,
            candidate_limit=candidate_limit,
            anchor_images=anchor_images,
        )
    return _review_row(
        item,
        preview,
        image_path=image_path,
        candidate_limit=candidate_limit,
        candidate_crop_paths=candidate_crop_paths,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export target-preview overlays and a target-selection template for manual review.")
    parser.add_argument("batch_json", nargs="+", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default=datetime.now().strftime("target-review-%Y%m%d-%H%M%S"))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--candidate-limit", type=int, default=6)
    parser.add_argument("--frontend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--frames-root", type=Path, default=None, help="Optional local uploads root containing {analysis_id}/frames.")
    parser.add_argument("--include-completed", action="store_true")
    parser.add_argument(
        "--latest-by-video",
        action="store_true",
        help="Keep only the latest row per video before filtering awaiting/completed status.",
    )
    parser.add_argument("--only", action="append", default=[], help="Limit export to a video name/stem or analysis id. Can be repeated.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows to export after filtering.")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of target previews to fetch in parallel.")
    args = parser.parse_args()

    output_dir = args.output_dir / args.label
    overlay_dir = output_dir / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    only_filters = {str(value).strip().lower() for value in args.only if str(value).strip()}
    batch_items = _batch_items(args.batch_json)
    if args.latest_by_video:
        batch_items = _latest_items_by_video(batch_items)
    items: list[dict[str, Any]] = []
    for item in batch_items:
        if not args.include_completed and str(item.get("status") or "") != "awaiting_target_selection":
            continue
        analysis_id = str(item.get("analysis_id") or "")
        if not analysis_id:
            continue
        if not _matches_only_filters(item, only_filters):
            continue
        items.append(item)
        if args.limit is not None and len(items) >= args.limit:
            break

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    workers = max(1, int(args.concurrency or 1))
    if workers == 1:
        for item in items:
            try:
                rows.append(
                    _export_one_review_row(
                        item,
                        base_url=args.base_url,
                        overlay_dir=overlay_dir,
                        frames_root=args.frames_root,
                        timeout=args.timeout,
                        candidate_limit=args.candidate_limit,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append({"video": item.get("video"), "analysis_id": item.get("analysis_id"), "error": f"{type(exc).__name__}: {exc}"})
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_by_index = {
                executor.submit(
                    _export_one_review_row,
                    item,
                    base_url=args.base_url,
                    overlay_dir=overlay_dir,
                    frames_root=args.frames_root,
                    timeout=args.timeout,
                    candidate_limit=args.candidate_limit,
                ): (index, item)
                for index, item in enumerate(items)
            }
            completed: list[tuple[int, dict[str, Any]]] = []
            for future in as_completed(future_by_index):
                index, item = future_by_index[future]
                try:
                    completed.append((index, future.result()))
                except Exception as exc:  # noqa: BLE001
                    failures.append({"video": item.get("video"), "analysis_id": item.get("analysis_id"), "error": f"{type(exc).__name__}: {exc}"})
            rows = [row for _, row in sorted(completed, key=lambda item: item[0])]

    review_json = output_dir / "target-preview-review.json"
    template_json = output_dir / "target-selection-template.json"
    review_md = output_dir / "target-preview-review.md"
    html_index = output_dir / "index.html"
    contact_sheet = output_dir / "contact-sheet.jpg"
    review_json.write_text(
        json.dumps({"summary": _review_summary(rows), "rows": rows, "failures": failures}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_selection_template(rows, template_json)
    _write_markdown(rows, review_md, label=args.label, template_path=template_json)
    _write_html_index(
        rows,
        html_index,
        label=args.label,
        frontend_url=args.frontend_url,
        template_path=template_json,
        review_json_path=review_json,
        review_md_path=review_md,
    )
    _write_contact_sheet(rows, contact_sheet)

    print(
        json.dumps(
            {
                "rows": len(rows),
                "failures": failures,
                "review_json": str(review_json),
                "review_md": str(review_md),
                "html_index": str(html_index),
                "selection_template": str(template_json),
                "contact_sheet": str(contact_sheet) if contact_sheet.exists() else None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
