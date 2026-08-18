from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.config import RuntimeConfig
from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore
from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.g2_baseline import G2BaselineStore, G2FreezeError
from app.analysis_v2.evaluation.pilot_evaluator import PilotPredictionBundle
from app.analysis_v2.evaluation.pilot_store import PilotEvaluationStore, collection_progress
from app.analysis_v2.evaluation.source_media import SourceMediaError, create_browser_playback, extract_source_frame_bytes, probe_source, source_frame_at, source_frame_reference_at, source_frame_reference_at_pts
from app.database import get_session
from app.routers.capabilities import get_runtime_config
from app.services.parent_access import require_parent_pin


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenCatalogSummary(_StrictResponse):
    dataset_id: str
    schema_version: Literal["golden-dataset.v2"]
    revision: int
    status: Literal["empty", "ready", "invalid-source", "schema-incompatible"]
    source_count: int
    event_count: int
    profile_counts: list["GoldenCount"]
    observability_counts: list["GoldenCount"]
    strata_counts: list["GoldenCount"]
    duplicate_sources: list[str]


class GoldenSchemaResponse(_StrictResponse):
    schema_version: Literal["golden-dataset.v2"]
    supported_schema_versions: list[str]
    migration_policy: Literal["future-v2-only"]
    historical_debug_pool: Literal["not-imported"]


class GoldenAggregateCounts(_StrictResponse):
    source_count: int
    event_count: int
    profile_counts: list["GoldenCount"]
    observability_counts: list["GoldenCount"]
    strata_counts: list["GoldenCount"]


class GoldenCount(_StrictResponse):
    key: str
    count: int


class GoldenGateTemplate(_StrictResponse):
    gate: Literal["G1"]
    status: Literal["not-run"]
    gate_policy_version: Literal["golden-gate-policy.v2"]
    evidence_scope: Literal["limited_sample"]
    required_source_videos: int
    required_valid_events: int
    profile_minimums: dict[str, int]
    required_new_events: int
    pose_frame_range: list[int]
    g2_event_range: list[int]
    g2_profile_ranges: dict[str, list[int]]


class GoldenSanitizedExport(_StrictResponse):
    schema_version: Literal["golden-sanitized-summary.v1"]
    dataset_id: str
    golden_schema_version: Literal["golden-dataset.v2"]
    revision: int
    aggregate: GoldenAggregateCounts
    redacted_aliases: list[str]
    gate_template: GoldenGateTemplate


class GoldenSourceView(_StrictResponse):
    source_sha256: str
    duration_pts: float
    width: int
    height: int
    timebase: dict[str, object]
    recording_session_id: str
    grouping_id: str
    redacted_alias: str
    source_frame_count: int | None
    average_fps: float | None
    nominal_fps: float | None
    display_rotation_degrees: Literal[0, 90, 180, 270]
    source_timeline: dict[str, object] | None = None


class GoldenWorkspaceResponse(_StrictResponse):
    dataset_id: str
    revision: int
    sources: list[GoldenSourceView]
    events: list[dict[str, object]]
    tracks: list[dict[str, object]]
    poses: list[dict[str, object]]


class GoldenAnnotationSaveRequest(_StrictResponse):
    expected_revision: int = Field(ge=1)
    annotator_alias: str = Field(min_length=1, max_length=160)
    change_note: str | None = Field(default=None, max_length=500)
    events: list[dict[str, object]]
    tracks: list[dict[str, object]]
    poses: list[dict[str, object]]


class GoldenSourceUpdateRequest(_StrictResponse):
    expected_revision: int = Field(ge=1)
    annotator_alias: str = Field(min_length=1, max_length=160)
    recording_session_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
    grouping_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
    redacted_alias: str = Field(min_length=1, max_length=160)


class GoldenSourceDeleteRequest(_StrictResponse):
    expected_revision: int = Field(ge=1)
    annotator_alias: str = Field(min_length=1, max_length=160)
    confirmation: Literal["delete_source_and_labels"]


class GoldenReviewItem(_StrictResponse):
    event_id: str
    status: Literal["incomplete", "low-confidence", "ambiguous", "double-review-required"]
    message: str


class GoldenFrameIdentity(_StrictResponse):
    source_frame_index: int
    pts: float
    duration: float | None


class PilotEvaluationStatus(_StrictResponse):
    status: Literal["not_run", "running", "waiting_for_owner_labels", "invalid_labels", "failed", "passed_for_pilot_only"]
    evaluator_version: str
    diagnostic_only: Literal[True]
    message: str | None = None
    result_fingerprint: str | None = None
    leakage_fields: list[str] = Field(default_factory=list)
    progress: dict[str, Any] | None = None
    gate_policy_version: Literal["golden-gate-policy.v1", "golden-gate-policy.v2"] | None = None
    evidence_scope: Literal["limited_sample"] | None = None


class GoldenReviewAttestationRequest(_StrictResponse):
    reviewer_alias: str = Field(min_length=1, max_length=160)
    review_type: Literal["delayed_relabel", "ambiguous_rotation", "frozen_identity_crossing"]
    note: str | None = Field(default=None, max_length=500)
    rotation_definition: Literal["airborne_body_rotation", "competition_naming", "observed_spin_rotation"] | None = None
    review_start_pts: float | None = Field(default=None, ge=0)
    review_end_pts: float | None = Field(default=None, ge=0)
    review_method: Literal["source_frame_step"] = "source_frame_step"

    @model_validator(mode="after")
    def valid_rotation_review(self) -> "GoldenReviewAttestationRequest":
        if self.review_type == "ambiguous_rotation":
            if self.rotation_definition is None or self.review_start_pts is None or self.review_end_pts is None:
                raise ValueError("ambiguous rotation review requires definition and exact source PTS interval")
            if self.review_end_pts <= self.review_start_pts:
                raise ValueError("ambiguous rotation review interval must be ordered")
        return self


class G2FreezeRequest(_StrictResponse):
    confirmation: str
    legacy_pipeline_fingerprint: str = Field(min_length=1, max_length=256)


class G2StatusResponse(_StrictResponse):
    schema_version: Literal["golden-g2-status.v1"] = "golden-g2-status.v1"
    gate: Literal["G2"] = "G2"
    gate_policy_version: Literal["golden-gate-policy.v1", "golden-gate-policy.v2"]
    evidence_scope: Literal["limited_sample"]
    status: Literal["collecting", "ready_to_freeze", "frozen_waiting_for_baseline", "baseline_recorded"]
    event_count: int
    required_event_range: list[int]
    profile_ranges: dict[str, list[int]]
    distribution: dict[str, Any]
    profiles: dict[str, Any] | None = None
    split_issues: list[str] = Field(default_factory=list)
    required_splits_present: bool | None = None
    ready_to_freeze: bool | None = None
    dataset_revision: int | None = None
    dataset_fingerprint: str | None = None
    legacy_pipeline_fingerprint: str | None = None
    baseline_result_fingerprint: str | None = None
    release_claim: Literal[False] = False


router = APIRouter(prefix="/api/golden/v2", tags=["golden-v2"])


def get_golden_store(config: RuntimeConfig = Depends(get_runtime_config)) -> GoldenCatalogStore:
    return GoldenCatalogStore(config.runtime_paths["golden"])


def get_pilot_store(store: GoldenCatalogStore = Depends(get_golden_store)) -> PilotEvaluationStore:
    return PilotEvaluationStore(store)


def get_g2_store(store: GoldenCatalogStore = Depends(get_golden_store)) -> G2BaselineStore:
    return G2BaselineStore(store)


async def require_golden_parent(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> None:
    await require_parent_pin(session, x_parent_pin)


@router.get("/catalog", response_model=GoldenCatalogSummary)
async def get_golden_catalog(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenCatalogSummary:
    return _catalog_response(store.catalog_summary())


@router.get("/schema", response_model=GoldenSchemaResponse)
async def get_golden_schema(_: None = Depends(require_golden_parent)) -> GoldenSchemaResponse:
    return GoldenSchemaResponse(
        schema_version="golden-dataset.v2",
        supported_schema_versions=["golden-dataset.v2"],
        migration_policy="future-v2-only",
        historical_debug_pool="not-imported",
    )


@router.get("/revisions/current", response_model=GoldenCatalogSummary)
async def get_golden_revision(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenCatalogSummary:
    return _catalog_response(store.catalog_summary())


@router.get("/workspace", response_model=GoldenWorkspaceResponse)
async def get_golden_workspace(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenWorkspaceResponse:
    dataset = store.ensure_initialized()
    return _workspace_response(dataset, store)


@router.get("/sources/{source_sha256}/media")
async def get_golden_source_media(
    source_sha256: str, _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> FileResponse:
    try:
        path = store.source_playback_path(source_sha256)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Private Golden source media is unavailable.") from exc
    return FileResponse(path, media_type="video/mp4", filename="private-golden-source.mp4")


@router.get("/sources/{source_sha256}/frames/by-pts", response_model=GoldenFrameIdentity)
async def get_golden_frame_identity_by_pts(
    source_sha256: str, pts: float = Query(..., ge=0), _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenFrameIdentity:
    try:
        reference = source_frame_reference_at_pts(store.source_media_path(source_sha256), pts)
        if reference.pts_sec is None:
            raise SourceMediaError("Requested source PTS has no timestamp")
    except SourceMediaError as exc:
        raise HTTPException(status_code=404, detail="Requested source PTS is unavailable.") from exc
    return GoldenFrameIdentity(source_frame_index=reference.source_frame_index, pts=reference.pts_sec, duration=reference.duration_sec)


@router.get("/sources/{source_sha256}/frames/{frame_index}", response_model=GoldenFrameIdentity)
async def get_golden_frame_identity(
    source_sha256: str, frame_index: int, _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenFrameIdentity:
    try:
        frame = source_frame_at(store.source_media_path(source_sha256), frame_index)
    except SourceMediaError as exc:
        raise HTTPException(status_code=404, detail="Requested source frame is unavailable.") from exc
    return GoldenFrameIdentity(source_frame_index=frame.index, pts=frame.pts, duration=frame.duration)


@router.get("/sources/{source_sha256}/frames/{frame_index}/image")
async def get_golden_source_frame_image(
    source_sha256: str, frame_index: int, _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> Response:
    try:
        payload = extract_source_frame_bytes(store.source_media_path(source_sha256), frame_index)
    except SourceMediaError as exc:
        raise HTTPException(status_code=404, detail="Requested source frame image is unavailable.") from exc
    return Response(content=payload, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/sources/import", response_model=GoldenSourceView, status_code=status.HTTP_201_CREATED)
async def import_golden_source(
    file: UploadFile = File(...),
    recording_session_id: str = Form(..., pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$"),
    grouping_id: str = Form(..., pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$"),
    redacted_alias: str = Form(..., min_length=1, max_length=160),
    expected_revision: int = Form(..., ge=1),
    annotator_alias: str = Form(..., min_length=1, max_length=160),
    _: None = Depends(require_golden_parent),
    store: GoldenCatalogStore = Depends(get_golden_store),
) -> GoldenSourceView:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".avi"}:
        raise HTTPException(status_code=400, detail="Unsupported private video format.")
    temporary = store.videos_dir / f".import-{uuid4().hex}{suffix}"
    final: Path | None = None
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        metadata = probe_source(temporary)
        current = store.ensure_initialized()
        if current.revision.revision != expected_revision:
            raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": current.revision.revision})
        if any(source.source_sha256 == metadata.source_sha256 for source in current.sources):
            raise HTTPException(status_code=409, detail={"code": "duplicate_source", "source_sha256": metadata.source_sha256})
        final_name = f"{metadata.source_sha256}{suffix}"
        final = store.videos_dir / final_name
        temporary.replace(final)
        create_browser_playback(final, store.videos_dir / f"{metadata.source_sha256}.playback.mp4")
        source = {
            "source_sha256": metadata.source_sha256, "duration_pts": metadata.duration_pts,
            "width": metadata.width, "height": metadata.height,
            "timebase": {"numerator": metadata.timebase_numerator, "denominator": metadata.timebase_denominator, "source_fps": metadata.nominal_fps, "is_vfr": metadata.is_vfr},
            "private_source_reference": f"videos/{final_name}", "recording_session_id": recording_session_id,
            "grouping_id": grouping_id, "redacted_alias": redacted_alias,
            "source_frame_count": metadata.source_frame_count, "average_fps": metadata.average_fps,
            "nominal_fps": metadata.nominal_fps, "display_rotation_degrees": metadata.display_rotation_degrees,
        }
        updated = _next_dataset(current, expected_revision, annotator_alias, "source imported", touch_labels=False, sources=[*current.sources, source])
        store.save(updated, expected_revision=expected_revision)
        get_pilot_store(store).invalidate("Golden sources changed. Run the pilot evaluator again after labeling is complete.")
        return _source_view(updated.sources[-1], store)
    except SourceMediaError as exc:
        raise HTTPException(status_code=400, detail="Unable to read private source metadata.") from exc
    except Exception:
        # Never leave an unregistered private copy after an interrupted catalog write.
        if final is not None:
            final.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


@router.patch("/sources/{source_sha256}", response_model=GoldenWorkspaceResponse)
async def update_golden_source(
    source_sha256: str,
    payload: GoldenSourceUpdateRequest,
    _: None = Depends(require_golden_parent),
    store: GoldenCatalogStore = Depends(get_golden_store),
) -> GoldenWorkspaceResponse:
    current = store.ensure_initialized()
    if current.revision.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": current.revision.revision})
    if not any(source.source_sha256 == source_sha256 for source in current.sources):
        raise HTTPException(status_code=404, detail="Golden source is unavailable.")
    sources = [
        {
            **source.model_dump(mode="json"),
            "recording_session_id": payload.recording_session_id,
            "grouping_id": payload.grouping_id,
            "redacted_alias": payload.redacted_alias,
        }
        if source.source_sha256 == source_sha256
        else source.model_dump(mode="json")
        for source in current.sources
    ]
    updated = _next_dataset(
        current,
        payload.expected_revision,
        payload.annotator_alias,
        "source metadata updated",
        touch_labels=False,
        sources=sources,
    )
    store.save(updated, expected_revision=payload.expected_revision)
    get_pilot_store(store).invalidate("Golden source grouping changed. Run the pilot evaluator again after labeling is complete.")
    return _workspace_response(updated, store)


@router.delete("/sources/{source_sha256}", response_model=GoldenWorkspaceResponse)
async def delete_golden_source(
    source_sha256: str,
    payload: GoldenSourceDeleteRequest,
    _: None = Depends(require_golden_parent),
    store: GoldenCatalogStore = Depends(get_golden_store),
) -> GoldenWorkspaceResponse:
    current = store.ensure_initialized()
    if current.revision.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": current.revision.revision})
    source = next((item for item in current.sources if item.source_sha256 == source_sha256), None)
    if source is None:
        raise HTTPException(status_code=404, detail="Golden source is unavailable.")
    event_ids = {event.event_id for event in current.events if event.source_sha256 == source_sha256}
    media_path = store.source_media_path(source_sha256)
    updated = _next_dataset(
        current,
        payload.expected_revision,
        payload.annotator_alias,
        "source and labels deleted",
        touch_labels=False,
        sources=[item.model_dump(mode="json") for item in current.sources if item.source_sha256 != source_sha256],
        events=[item.model_dump(mode="json") for item in current.events if item.event_id not in event_ids],
        tracks=[item.model_dump(mode="json") for item in current.tracks if item.event_id not in event_ids],
        poses=[item.model_dump(mode="json") for item in current.poses if item.event_id not in event_ids],
    )
    store.save(updated, expected_revision=payload.expected_revision)
    media_path.unlink(missing_ok=True)
    for event_id in event_ids:
        (store.suggestions_dir / f"{event_id}.json").unlink(missing_ok=True)
        (store.reviews_dir / f"{event_id}.json").unlink(missing_ok=True)
    get_pilot_store(store).invalidate("Golden sources changed. Run the pilot evaluator again after labeling is complete.")
    return _workspace_response(updated, store)


@router.put("/annotations", response_model=GoldenWorkspaceResponse)
async def save_golden_annotations(
    payload: GoldenAnnotationSaveRequest,
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenWorkspaceResponse:
    current = store.ensure_initialized()
    if current.revision.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": current.revision.revision})
    try:
        updated = _next_dataset(current, payload.expected_revision, payload.annotator_alias, payload.change_note, events=payload.events, tracks=payload.tracks, poses=payload.poses)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Annotation is incomplete or contradictory; nothing was saved.") from exc
    store.save(updated, expected_revision=payload.expected_revision)
    get_pilot_store(store).invalidate("Golden labels changed. Run the pilot evaluator again after labeling is complete.")
    return _workspace_response(updated, store)


@router.get("/events/{event_id}/history")
async def get_golden_event_history(
    event_id: str, _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> list[dict[str, Any]]:
    return store.event_history(event_id)


@router.post("/events/{event_id}/review-attestations", status_code=status.HTTP_201_CREATED)
async def add_golden_review_attestation(
    event_id: str,
    payload: GoldenReviewAttestationRequest,
    _: None = Depends(require_golden_parent),
    store: GoldenCatalogStore = Depends(get_golden_store),
) -> dict[str, object]:
    event = next((item for item in store.read().events if item.event_id == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Golden event is unavailable.")
    history_times = [event.revision.created_at]
    for snapshot in store.event_history(event_id):
        created_at = snapshot.get("event", {}).get("revision", {}).get("created_at")
        if created_at:
            history_times.append(datetime.fromisoformat(str(created_at).replace("Z", "+00:00")))
    if payload.review_type == "delayed_relabel" and datetime.now(timezone.utc) - min(history_times) < timedelta(hours=24):
        raise HTTPException(status_code=422, detail="Delayed re-label review requires at least 24 hours after the original label.")
    if payload.review_type != "delayed_relabel" and payload.reviewer_alias == event.revision.annotator_alias:
        raise HTTPException(status_code=422, detail="Double review requires a different reviewer alias.")
    if payload.review_type == "ambiguous_rotation":
        rotation = event.jump.rotation if event.jump else event.spin.rotation if event.spin else None
        if not rotation or (rotation.observability == "observable" and rotation.observed_turns_min == rotation.observed_turns_max):
            raise HTTPException(status_code=422, detail="This event does not require ambiguous-rotation review.")
        label_reviewer = event.field_revisions.get("rotation", event.revision).annotator_alias
        if payload.reviewer_alias == label_reviewer:
            raise HTTPException(status_code=422, detail="Ambiguous rotation requires a different reviewer.")
        if payload.rotation_definition != rotation.definition:
            raise HTTPException(status_code=422, detail="Rotation review definition does not match the current label.")
        if payload.review_start_pts < event.start_pts or payload.review_end_pts > event.end_pts:
            raise HTTPException(status_code=422, detail="Rotation review interval must stay inside the event source PTS interval.")
        expected_start = rotation.review_start_pts if rotation.review_start_pts is not None else event.start_pts
        expected_end = rotation.review_end_pts if rotation.review_end_pts is not None else event.end_pts
        if abs(payload.review_start_pts - expected_start) > 1e-6 or abs(payload.review_end_pts - expected_end) > 1e-6:
            raise HTTPException(status_code=422, detail="Rotation review must use the current label's exact source PTS interval.")
    if payload.review_type == "frozen_identity_crossing" and not (event.split == "frozen_test" and any(item.category == "crossing" for item in event.challenge_intervals)):
        raise HTTPException(status_code=422, detail="This event does not require frozen crossing review.")
    store.add_review_attestation(event_id, {"review_type": payload.review_type, "reviewer_alias": payload.reviewer_alias, "reviewed_at": datetime.now(timezone.utc).isoformat(), "note": payload.note, "event_revision": event.revision.revision, "rotation_definition": payload.rotation_definition, "review_start_pts": payload.review_start_pts, "review_end_pts": payload.review_end_pts, "review_method": payload.review_method})
    return {"event_id": event_id, "review_type": payload.review_type, "recorded": True}


@router.get("/events/{event_id}/suggestions")
async def get_golden_event_suggestions(
    event_id: str, _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> list[dict[str, Any]]:
    event = next((item for item in store.read().events if item.event_id == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Golden event is unavailable.")
    # Frozen first pass is a server-side authorization boundary, never a CSS choice.
    if event.split == "frozen_test" and event.revision.revision <= 2:
        raise HTTPException(status_code=403, detail="Suggestions are unavailable during frozen-test first pass.")
    return store.read_suggestions(event_id)


@router.get("/review-queue", response_model=list[GoldenReviewItem])
async def get_golden_review_queue(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> list[GoldenReviewItem]:
    return _review_queue(store.ensure_initialized(), store)


@router.get("/evaluator/progress")
async def get_pilot_progress(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> dict[str, Any]:
    return collection_progress(store.ensure_initialized(), store)


@router.get("/evaluator/status", response_model=PilotEvaluationStatus)
async def get_pilot_evaluator_status(
    _: None = Depends(require_golden_parent), evaluator: PilotEvaluationStore = Depends(get_pilot_store)
) -> PilotEvaluationStatus:
    return PilotEvaluationStatus.model_validate(evaluator.status())


@router.post("/evaluator/runs", response_model=PilotEvaluationStatus)
async def run_pilot_evaluator(
    payload: PilotPredictionBundle,
    diagnostic_snapshot: bool = Query(default=False),
    _: None = Depends(require_golden_parent),
    evaluator: PilotEvaluationStore = Depends(get_pilot_store),
) -> PilotEvaluationStatus:
    return PilotEvaluationStatus.model_validate(evaluator.run(payload, diagnostic_snapshot=diagnostic_snapshot))


@router.get("/evaluator/result")
async def get_pilot_evaluator_result(
    _: None = Depends(require_golden_parent), evaluator: PilotEvaluationStore = Depends(get_pilot_store)
) -> dict[str, Any]:
    result = evaluator.sanitized_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No pilot diagnostic result is available.")
    return result


@router.get("/evaluator/events/{alias}")
async def get_pilot_event_diagnostic(
    alias: str,
    _: None = Depends(require_golden_parent),
    evaluator: PilotEvaluationStore = Depends(get_pilot_store),
) -> dict[str, Any]:
    result = evaluator.private_event(alias)
    if result is None:
        raise HTTPException(status_code=404, detail="Private pilot event diagnostic is unavailable.")
    return result


@router.get("/sanitized-export", response_model=GoldenSanitizedExport)
async def get_golden_sanitized_export(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenSanitizedExport:
    payload = store.sanitized_export()
    aggregate = payload["aggregate"]
    return GoldenSanitizedExport(
        schema_version="golden-sanitized-summary.v1",
        dataset_id=str(payload["dataset_id"]),
        golden_schema_version="golden-dataset.v2",
        revision=int(payload["revision"]),
        aggregate=GoldenAggregateCounts(
            source_count=int(aggregate["source_count"]),
            event_count=int(aggregate["event_count"]),
            profile_counts=[GoldenCount(key=key, count=count) for key, count in aggregate["profile_counts"].items()],
            observability_counts=[GoldenCount(key=key, count=count) for key, count in aggregate["observability_counts"].items()],
            strata_counts=[GoldenCount(key=key, count=count) for key, count in aggregate["strata_counts"].items()],
        ),
        redacted_aliases=list(payload["redacted_aliases"]),
        gate_template=GoldenGateTemplate.model_validate(payload["gate_template"]),
    )


@router.get("/g2/status", response_model=G2StatusResponse)
async def get_g2_status(
    _: None = Depends(require_golden_parent),
    store: GoldenCatalogStore = Depends(get_golden_store),
    g2_store: G2BaselineStore = Depends(get_g2_store),
) -> G2StatusResponse:
    return G2StatusResponse.model_validate(g2_store.public_status(store.ensure_initialized()))


@router.post("/g2/freeze", response_model=G2StatusResponse)
async def freeze_g2_dataset(
    payload: G2FreezeRequest,
    _: None = Depends(require_golden_parent),
    store: GoldenCatalogStore = Depends(get_golden_store),
    g2_store: G2BaselineStore = Depends(get_g2_store),
) -> G2StatusResponse:
    if payload.confirmation != "freeze_g2_dataset":
        raise HTTPException(status_code=422, detail="Freezing G2 requires explicit confirmation.")
    dataset = store.ensure_initialized()
    try:
        g2_store.freeze(dataset, legacy_pipeline_fingerprint=payload.legacy_pipeline_fingerprint)
        return G2StatusResponse.model_validate(g2_store.public_status(dataset))
    except G2FreezeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _catalog_response(payload: dict[str, object]) -> GoldenCatalogSummary:
    return GoldenCatalogSummary(
        dataset_id=str(payload["dataset_id"]),
        schema_version="golden-dataset.v2",
        revision=int(payload["revision"]),
        status=str(payload["status"]),
        source_count=int(payload["source_count"]),
        event_count=int(payload["event_count"]),
        profile_counts=_counts(payload["profile_counts"]),
        observability_counts=_counts(payload["observability_counts"]),
        strata_counts=_counts(payload["strata_counts"]),
        duplicate_sources=list(payload["duplicate_sources"]),
    )


def _counts(value: object) -> list[GoldenCount]:
    if not isinstance(value, dict):
        return []
    return [GoldenCount(key=str(key), count=int(count)) for key, count in value.items()]


def _source_view(source: Any, store: GoldenCatalogStore | None = None) -> GoldenSourceView:
    return GoldenSourceView(
        source_sha256=source.source_sha256, duration_pts=source.duration_pts, width=source.width, height=source.height,
        timebase=source.timebase.model_dump(), recording_session_id=source.recording_session_id, grouping_id=source.grouping_id,
        redacted_alias=source.redacted_alias, source_frame_count=source.source_frame_count, average_fps=source.average_fps,
        nominal_fps=source.nominal_fps, display_rotation_degrees=source.display_rotation_degrees,
        source_timeline=source.source_timeline,
    )


def _workspace_response(dataset: GoldenDatasetV2, store: GoldenCatalogStore | None = None) -> GoldenWorkspaceResponse:
    return GoldenWorkspaceResponse(
        dataset_id=dataset.dataset_id, revision=dataset.revision.revision, sources=[_source_view(item, store) for item in dataset.sources],
        events=[item.model_dump(mode="json") for item in dataset.events], tracks=[item.model_dump(mode="json") for item in dataset.tracks],
        poses=[item.model_dump(mode="json") for item in dataset.poses],
    )


def _next_dataset(current: GoldenDatasetV2, expected_revision: int, annotator_alias: str, change_note: str | None, *, touch_labels: bool = True, **changes: Any) -> GoldenDatasetV2:
    revision = {"revision": expected_revision + 1, "parent_revision": expected_revision, "annotator_alias": annotator_alias, "provenance": "human_annotation", "change_note": change_note}
    payload = current.model_dump(mode="json")
    payload.update(changes)
    payload["revision"] = revision
    if touch_labels:
        for event in payload.get("events", []):
            if isinstance(event, dict):
                event["revision"] = revision
                event["field_revisions"] = {key: revision for key in ("profile", "interval", "observability", "main_skater", "moments", "rotation", "boxes", "pose")}
        for track in payload.get("tracks", []):
            if isinstance(track, dict):
                track["revision"] = revision
        for pose in payload.get("poses", []):
            if isinstance(pose, dict):
                pose["revision"] = revision
    return GoldenDatasetV2.model_validate(payload)


def _review_queue(dataset: GoldenDatasetV2, store: GoldenCatalogStore | None = None) -> list[GoldenReviewItem]:
    items: list[GoldenReviewItem] = []
    for event in dataset.events:
        if not event.main_skater_confirmed:
            items.append(GoldenReviewItem(event_id=event.event_id, status="incomplete", message="Confirm the main skater before this event can be reviewed."))
        if event.annotator_confidence < 0.7:
            items.append(GoldenReviewItem(event_id=event.event_id, status="low-confidence", message="Low annotator confidence needs a follow-up review."))
        if event.ambiguity_tags:
            items.append(GoldenReviewItem(event_id=event.event_id, status="ambiguous", message="Ambiguity tags require an explicit reviewer decision."))
        rotation = event.jump.rotation if event.jump else event.spin.rotation if event.spin else None
        rotation_reviews = store.review_attestations(event.event_id) if store is not None else []
        label_reviewer = event.field_revisions.get("rotation", event.revision).annotator_alias
        rotation_reviewed = any(
            review.get("review_type") == "ambiguous_rotation"
            and review.get("reviewer_alias") != label_reviewer
            and review.get("event_revision") == event.revision.revision
            and review.get("rotation_definition") == rotation.definition
            and review.get("review_method") == "source_frame_step"
            and abs(float(review.get("review_start_pts", -1)) - (rotation.review_start_pts if rotation.review_start_pts is not None else event.start_pts)) <= 1e-6
            and abs(float(review.get("review_end_pts", -1)) - (rotation.review_end_pts if rotation.review_end_pts is not None else event.end_pts)) <= 1e-6
            for review in rotation_reviews
        ) if rotation else False
        if rotation and (rotation.observability != "observable" or rotation.observed_turns_min != rotation.observed_turns_max) and not rotation_reviewed:
            items.append(GoldenReviewItem(event_id=event.event_id, status="double-review-required", message="Ambiguous rotation requires a second reviewer."))
        if event.split == "frozen_test" and any(challenge.category == "crossing" for challenge in event.challenge_intervals):
            items.append(GoldenReviewItem(event_id=event.event_id, status="double-review-required", message="Frozen-test identity crossings require a second reviewer."))
    return items
