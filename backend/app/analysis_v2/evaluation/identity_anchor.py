from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityAnchorBBox(_StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def stays_inside_frame(self) -> "IdentityAnchorBBox":
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("identity anchor bbox must stay inside the normalized frame")
        return self


class ParentIdentityAnchor(_StrictModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    bbox: IdentityAnchorBBox
    authority: Literal["parent_confirmed"] = "parent_confirmed"


class ParentIdentityAnchorManifest(_StrictModel):
    schema_version: Literal["parent-identity-anchor-manifest.v1"] = "parent-identity-anchor-manifest.v1"
    diagnostic_only: Literal[True] = True
    release_claim: Literal[False] = False
    evaluated_targets_consumed: Literal[False] = False
    anchors: tuple[ParentIdentityAnchor, ...] = ()

    @model_validator(mode="after")
    def sources_are_unique(self) -> "ParentIdentityAnchorManifest":
        sources = [item.source_sha256 for item in self.anchors]
        if len(sources) != len(set(sources)):
            raise ValueError("identity anchor manifest contains duplicate sources")
        if list(self.anchors) != sorted(self.anchors, key=lambda item: item.source_sha256):
            raise ValueError("identity anchors must be source ordered")
        return self

    def by_source(self) -> dict[str, ParentIdentityAnchor]:
        return {item.source_sha256: item for item in self.anchors}


def build_parent_identity_anchor_manifest(workspace: Mapping[str, Any]) -> ParentIdentityAnchorManifest:
    """Export one upstream parent-confirmed identity anchor per source.

    The manifest deliberately excludes event IDs, action profiles, event
    windows, semantic moments, rotation targets, and later tracking frames.
    """

    earliest: dict[str, ParentIdentityAnchor] = {}
    tracks = workspace.get("tracks")
    if not isinstance(tracks, Sequence) or isinstance(tracks, (str, bytes)):
        tracks = ()
    for item in tracks:
        if not isinstance(item, Mapping) or str(item.get("state") or "") != "confirmed":
            continue
        source_hash = str(item.get("source_sha256") or "")
        bbox = _normalized_bbox(item.get("bbox"))
        if bbox is None:
            continue
        try:
            anchor = ParentIdentityAnchor(
                source_sha256=source_hash,
                source_frame_index=int(item.get("source_frame_index")),
                pts_sec=float(item.get("pts")),
                bbox=bbox,
            )
        except (TypeError, ValueError):
            continue
        current = earliest.get(source_hash)
        if current is None or (anchor.pts_sec, anchor.source_frame_index) < (current.pts_sec, current.source_frame_index):
            earliest[source_hash] = anchor
    return ParentIdentityAnchorManifest(anchors=tuple(sorted(earliest.values(), key=lambda item: item.source_sha256)))


def load_parent_identity_anchor_manifest(path: Path) -> ParentIdentityAnchorManifest:
    return ParentIdentityAnchorManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def target_lock_payload_from_parent_anchor(
    anchor: ParentIdentityAnchor,
    frame_names: Sequence[str],
    selected_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    index = _nearest_sample_index(anchor, selected_samples)
    index = max(0, min(index, max(0, len(frame_names) - 1)))
    return {
        "preview_frame": frame_names[index] if frame_names else None,
        "preview_frame_index": index,
        "candidates": [],
        "selected_candidate_id": None,
        "selected_bbox": anchor.bbox.model_dump(mode="json"),
        "lock_confidence": 1.0,
        "status": "manual",
        "manual_override": True,
        "identity_anchor_source": "parent_confirmed",
        "quality_flags": ["diagnostic_parent_confirmed_identity_anchor"],
    }


def _nearest_sample_index(anchor: ParentIdentityAnchor, samples: Sequence[Mapping[str, Any]]) -> int:
    ranked: list[tuple[tuple[float, float, int], int]] = []
    for index, item in enumerate(samples):
        try:
            frame = int(item.get("source_frame_index"))
        except (TypeError, ValueError):
            frame = anchor.source_frame_index
        try:
            pts = float(item.get("pts_sec", item.get("timestamp")))
        except (TypeError, ValueError):
            pts = anchor.pts_sec
        ranked.append(((abs(frame - anchor.source_frame_index), abs(pts - anchor.pts_sec), index), index))
    return min(ranked, default=((0, 0, 0), 0))[1]


def _normalized_bbox(value: Any) -> IdentityAnchorBBox | None:
    if not isinstance(value, Mapping):
        return None
    try:
        if all(key in value for key in ("left", "top", "right", "bottom")):
            left = float(value["left"])
            top = float(value["top"])
            right = float(value["right"])
            bottom = float(value["bottom"])
            return IdentityAnchorBBox(x=left, y=top, width=right - left, height=bottom - top)
        return IdentityAnchorBBox.model_validate(value)
    except (TypeError, ValueError):
        return None
