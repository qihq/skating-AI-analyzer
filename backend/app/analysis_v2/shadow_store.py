"""Compatibility adapter for the canonical end-to-end Shadow orchestrator.

The source of truth for manifests, stage checkpoints, queue artifacts, and
cleanup is :mod:`app.analysis_v2.orchestration`.  This adapter only translates
those dataclasses into the parent-facing API contracts; it does not introduce
another persistence layout.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.analysis_v2.config import RuntimeConfig
from app.analysis_v2.orchestration import (
    SHADOW_STAGE_ORDER,
    ShadowArtifactStore as CanonicalShadowArtifactStore,
    ShadowRun,
    ShadowStage,
    ShadowStageStatus,
    canonical_fingerprints,
    canonical_stage_fingerprints,
    content_hash,
    diff_runs,
    diff_legacy_to_shadow,
    fingerprint_changes,
    invalidation_for_fingerprint_changes,
)
from app.analysis_v2.shadow_contracts import (
    ShadowArtifactReference,
    ShadowReviewDecision,
    ShadowRunRecord,
    ShadowRunRequest,
    ShadowStageDiff,
    ShadowStageState,
    utc_now,
)


class ShadowStoreError(ValueError):
    pass


class ShadowRunNotFound(ShadowStoreError):
    pass


_STAGE_ALIASES = {"complete": "completed", "failed": "retryable", "invalid": "invalid", "pending": "pending"}


class ShadowArtifactStore:
    """Parent API adapter backed by canonical ``shadow/v2`` manifests."""

    def __init__(self, config_or_root: RuntimeConfig | Path) -> None:
        if isinstance(config_or_root, RuntimeConfig):
            config = config_or_root
            if not config.is_isolated or config.runtime_root is None:
                raise ShadowStoreError("Shadow runtime is not isolated")
            runtime_root = config.runtime_root
        else:
            runtime_root = Path(config_or_root)
        self.canonical = CanonicalShadowArtifactStore(runtime_root)
        self.root = self.canonical.root
        self.runs_dir = self.canonical.runs_root
        self.artifacts_dir = self.root
        self.audit_dir = self.canonical.audits_root
        self.ensure_initialized()
        self._coalesced_ids: set[str] = set()
        self._retry_targets: dict[str, str] = {}

    def ensure_initialized(self) -> None:
        self.canonical.ensure_layout()

    @property
    def _runtime_root(self) -> Path:
        return self.canonical.runtime_root

    @staticmethod
    def _safe(value: str) -> str:
        if not value or Path(value).name != value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ShadowStoreError("invalid Shadow identifier")
        return value

    @staticmethod
    def _pipeline_fingerprint(request: ShadowRunRequest) -> str:
        payload = {
            "source": request.source_fingerprint or request.source_video_hash,
            "model": request.model_fingerprint,
            "config": request.config_fingerprint,
            "prompt": request.prompt_fingerprint,
            "contract": request.contract_fingerprint,
        }
        return content_hash(payload)

    @staticmethod
    def _fingerprints(request: ShadowRunRequest) -> dict[str, str]:
        return canonical_fingerprints({
            "source": request.source_fingerprint or request.source_video_hash,
            "model": request.model_fingerprint,
            "config": request.config_fingerprint,
            "prompt": request.prompt_fingerprint,
            "contract": request.contract_fingerprint,
        })

    @staticmethod
    def _record(run: ShadowRun, *, coalesced: bool = False, retry_target: str | None = None) -> ShadowRunRecord:
        stages = [
            ShadowStageState(
                stage=stage.name,
                status={"completed": "complete", "retryable": "failed", "cancelled": "skipped"}.get(stage.status.value, stage.status.value),
                fingerprint=stage.fingerprint or None,
                input_hash=stage.input_hash or None,
                output_hash=stage.output_hash or None,
                dependency_hashes=dict(stage.dependency_hashes),
                error=stage.error_detail,
                retry_count=stage.retry_count,
                updated_at=stage.completed_at or stage.started_at or run.updated_at,
            )
            for stage in run.stages
        ]
        artifacts = []
        for stage in run.stages:
            if not stage.artifact_reference:
                continue
            artifact_id = f"{run.run_id}:{stage.name}"
            artifacts.append(ShadowArtifactReference(artifact_id=artifact_id, stage=stage.name, relative_path=stage.artifact_reference, fingerprint=stage.output_hash or None))
        status = {"completed": "complete", "failed": "failed", "pending": "queued"}.get(run.status, run.status)
        if status == "queued" and any(stage.status in {"complete", "failed", "invalid"} for stage in stages):
            status = "partial"
        diffs: list[ShadowStageDiff] = []
        first_divergent_stage = None
        if run.legacy_stage_fingerprints:
            comparison = diff_legacy_to_shadow(run.legacy_stage_fingerprints, run)
            first_divergent_stage = comparison.first_divergent_stage
            diffs = [
                ShadowStageDiff(
                    stage=item.stage,
                    status="unchanged" if item.equal else ("unexplained" if any(reason.startswith("missing_") for reason in item.reasons) else "different"),
                    legacy_fingerprint=item.left_fingerprint,
                    v2_fingerprint=item.right_fingerprint,
                    summary=None if item.equal else ", ".join(item.reasons),
                    details={"comparison": "legacy_vs_shadow", "reasons": list(item.reasons)},
                    first_divergent=item.first_divergent,
                )
                for item in comparison.stages
            ]
        return ShadowRunRecord(
            run_id=run.run_id,
            analysis_id=run.analysis_id,
            status=status,
            pipeline_fingerprint=run.pipeline_fingerprint,
            source_video_hash=run.source_identity.get("video_hash"),
            source_fingerprint=run.fingerprints.get("source") or run.source_identity.get("source_fingerprint") or run.source_identity.get("video_hash"),
            model_fingerprint=run.fingerprints.get("model"),
            config_fingerprint=run.fingerprints.get("config"),
            prompt_fingerprint=run.fingerprints.get("prompt"),
            contract_fingerprint=run.fingerprints.get("contract"),
            legacy_stage_fingerprints=dict(run.legacy_stage_fingerprints),
            created_at=run.created_at,
            updated_at=run.updated_at,
            requested_by="parent",
            coalesced=coalesced,
            retry_from_stage=retry_target or (run.first_invalid_stage if status in {"queued", "failed"} else None),
            first_divergent_stage=first_divergent_stage,
            stages=stages,
            diffs=diffs,
            artifacts=artifacts,
            downstream=ShadowArtifactStore.default_downstream(),
            notes=[{"author": "parent", "note": note, "created_at": run.updated_at} for note in run.reviewer_notes if not note.startswith("shadow-review:")],
            error=next((stage.error_detail for stage in run.stages if stage.error_detail), None),
        )

    def read(self, run_id: str) -> ShadowRunRecord:
        try:
            return self._record(self.canonical.load_run(self._safe(run_id)), coalesced=run_id in self._coalesced_ids, retry_target=self._retry_targets.get(run_id))
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ShadowRunNotFound(f"Shadow run {run_id!r} was not found") from exc

    def _load(self, run_id: str) -> ShadowRun:
        try:
            return self.canonical.load_run(self._safe(run_id))
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ShadowRunNotFound(f"Shadow run {run_id!r} was not found") from exc

    def create(self, request: ShadowRunRequest) -> ShadowRunRecord:
        key = self._pipeline_fingerprint(request)
        fingerprints = self._fingerprints(request)
        legacy_stage_fingerprints = canonical_stage_fingerprints(request.legacy_stage_fingerprints)
        for run in self.canonical.list_runs():
            if run.analysis_id != request.analysis_id or run.pipeline_fingerprint != key:
                continue
            if not request.force:
                self._coalesced_ids.add(run.run_id)
                return self._record(run, coalesced=True)
        run = ShadowRun.create(
            analysis_id=request.analysis_id,
            source_identity={"video_hash": request.source_video_hash or "", "source_fingerprint": request.source_fingerprint or ""},
            pipeline_fingerprint=key,
            fingerprints=fingerprints,
            legacy_stage_fingerprints=legacy_stage_fingerprints,
        )
        # Store-level duplicate requests coalesce by analysis + pipeline
        # above. Once a parent explicitly asks for ``force`` a new run must be
        # allowed to execute independently; include the generated run id in
        # the queue key so the canonical bounded queue cannot merge two
        # distinct diagnostic runs.
        run = replace(run, queue_key=f"{request.analysis_id}:{key}:{run.run_id}" if request.force else f"{request.analysis_id}:{key}")
        self.canonical.save_run(run)
        if request.note:
            self.add_note(run.run_id, {"author": request.requested_by, "note": request.note, "created_at": utc_now()})
            run = self._load(run.run_id)
        return self._record(run)

    def attach_legacy_stage_fingerprints(
        self,
        run_id: str,
        fingerprints: dict[str, str],
    ) -> ShadowRunRecord:
        """Attach a sanitized legacy baseline to an existing API run.

        Parent API creation persists the queue record before loading the
        detached legacy snapshot.  This small second write fills the hash-only
        baseline without ever copying legacy fields into the Shadow manifest.
        An explicitly supplied baseline remains authoritative.
        """
        run = self._load(run_id)
        if run.legacy_stage_fingerprints:
            return self._record(run, coalesced=run_id in self._coalesced_ids)
        baseline = canonical_stage_fingerprints(fingerprints)
        if not baseline:
            return self._record(run, coalesced=run_id in self._coalesced_ids)
        updated = replace(run, legacy_stage_fingerprints=baseline)
        self.canonical.save_run(updated)
        self.canonical.append_audit(
            run_id,
            {
                "kind": "legacy_stage_baseline_attached",
                "stage_count": len(baseline),
                "hashes_only": True,
            },
        )
        return self._record(updated, coalesced=run_id in self._coalesced_ids)

    def list_for_analysis(self, analysis_id: str) -> list[ShadowRunRecord]:
        runs = [run for run in self.canonical.list_runs() if run.analysis_id == analysis_id]
        return [self._record(run, coalesced=run.run_id in self._coalesced_ids, retry_target=self._retry_targets.get(run.run_id)) for run in sorted(runs, key=lambda item: item.updated_at, reverse=True)]

    def update_stage(self, run_id: str, stage: str, **changes: Any) -> ShadowRunRecord:
        run = self._load(run_id)
        current = run.stage(stage)
        status = changes.get("status", current.status.value)
        status = _STAGE_ALIASES.get(str(status), str(status))
        try:
            next_status = ShadowStageStatus(status)
        except ValueError as exc:
            raise ShadowStoreError(f"unknown stage status {status!r}") from exc
        updated = replace(
            current,
            status=next_status,
            output_hash=changes.get("output_hash", current.output_hash),
            input_hash=changes.get("input_hash", current.input_hash),
            fingerprint=changes.get("fingerprint", current.fingerprint),
            dependency_hashes=dict(changes.get("dependency_hashes", current.dependency_hashes) or {}),
            artifact_reference=changes.get("artifact_reference", current.artifact_reference),
            error_detail=changes.get("error", current.error_detail),
            error_code=changes.get("error_code", current.error_code),
            retry_count=changes.get("retry_count", current.retry_count),
            attempt=changes.get("attempt", current.attempt),
            started_at=changes.get("started_at", current.started_at),
            completed_at=utc_now() if next_status is ShadowStageStatus.COMPLETED else changes.get("completed_at", current.completed_at),
        )
        self.canonical.save_run(run.with_stage(updated))
        return self.read(run_id)

    def update_fingerprints(self, run_id: str, fingerprints: dict[str, str]) -> ShadowRunRecord:
        """Persist independent fingerprints and invalidate dependent stages."""
        run = self._load(run_id)
        updated = run.with_fingerprints(fingerprints)
        if updated is not run:
            self.canonical.save_run(updated)
            self.canonical.append_audit(
                run_id,
                {
                    "kind": "fingerprint_update",
                    "changed": list(fingerprint_changes(run.fingerprints, updated.fingerprints)),
                    "invalidated_from": updated.first_invalid_stage,
                    "at": utc_now(),
                },
            )
        return self.read(run_id)

    def retry(self, run_id: str, stage: str | None) -> ShadowRunRecord:
        run = self._load(run_id)
        target = stage or run.first_invalid_stage or SHADOW_STAGE_ORDER[0]
        self._retry_targets[run_id] = target
        self.canonical.save_run(run.invalidate(target, reason="parent_retry"))
        self.canonical.append_audit(run_id, {"kind": "retry", "stage": target, "at": utc_now()})
        return self.read(run_id)

    def recover_incomplete(self, run_id: str) -> ShadowRunRecord:
        """Mark stale running stages retryable and return the resume point.

        A process restart can leave a checkpoint in ``running`` with no
        corresponding worker.  Recovery is conservative: only those running
        checkpoints are invalidated; completed descendants remain reusable.
        """
        run = self._load(run_id)
        stale = [stage.name for stage in run.stages if stage.status is ShadowStageStatus.RUNNING]
        stale.extend(
            stage.name
            for stage in run.stages
            if stage.status is ShadowStageStatus.COMPLETED
            and stage.artifact_reference
            and not self.canonical._artifact_reference_exists(stage.artifact_reference)
        )
        if not stale:
            return self.read(run_id)
        target = min(stale, key=lambda item: SHADOW_STAGE_ORDER.index(item))
        recovered = run.invalidate(target, reason="restart_recovery")
        self.canonical.save_run(recovered)
        self.canonical.append_audit(run_id, {"kind": "restart_recovery", "stage": target, "at": utc_now()})
        self._retry_targets[run_id] = target
        return self.read(run_id)

    def cleanup(self, run_id: str) -> tuple[str, ...]:
        """Delete only rebuildable stage artifacts and retain the manifest/audit."""
        self._load(run_id)  # validate identifier and fail closed if absent
        removed = self.canonical.cleanup_rebuildable(self._safe(run_id))
        self.canonical.append_audit(
            run_id,
            {
                "kind": "cleanup",
                "removed": list(removed),
                "retained": ["run.json", "audit.jsonl", "source", "golden", "reviews", "corrections"],
                "at": utc_now(),
            },
        )
        return removed

    def stage_diffs(self, run_id: str, compare_to: str | None = None) -> tuple[str | None, list[ShadowStageDiff]]:
        current = self._load(run_id)
        # If a sanitized legacy baseline was attached to this run, compare the
        # run against that authority first.  This is the canonical Shadow
        # diff; comparing two Shadow runs remains available via ``compare_to``.
        if compare_to is None and current.legacy_stage_fingerprints:
            compared = diff_legacy_to_shadow(current.legacy_stage_fingerprints, current)
            output = [
                ShadowStageDiff(
                    stage=item.stage,
                    status="unchanged" if item.equal else ("unexplained" if "missing_" in ",".join(item.reasons) else "different"),
                    legacy_fingerprint=item.left_fingerprint,
                    v2_fingerprint=item.right_fingerprint,
                    summary=None if item.equal else ", ".join(item.reasons),
                    details={
                        "comparison": "legacy_vs_shadow",
                        "left_status": item.left_status,
                        "right_status": item.right_status,
                        "left_output_hash": item.left_output_hash,
                        "right_output_hash": item.right_output_hash,
                    },
                    first_divergent=item.first_divergent,
                )
                for item in compared.stages
            ]
            return compared.first_divergent_stage, output
        baseline: ShadowRun | None = self._load(compare_to) if compare_to else None
        if baseline is None:
            candidates = [item for item in self.canonical.list_runs() if item.analysis_id == current.analysis_id and item.run_id != current.run_id]
            if candidates:
                baseline = sorted(candidates, key=lambda item: item.updated_at, reverse=True)[0]
        if baseline is None:
            return None, [ShadowStageDiff(stage=name, status="unavailable", summary="No previous Shadow run to compare", details={"comparison": "read_only"}) for name in SHADOW_STAGE_ORDER]
        compared = diff_runs(baseline, current)
        output = [ShadowStageDiff(
            stage=item.stage,
            status="unchanged" if item.equal else "unexplained" if not item.reasons else "different",
            legacy_fingerprint=item.left_fingerprint,
            v2_fingerprint=item.right_fingerprint,
            summary=None if item.equal else ", ".join(item.reasons),
            details={"baseline_run_id": baseline.run_id, "current_run_id": current.run_id, "left_status": item.left_status, "right_status": item.right_status, "left_input_hash": item.left_input_hash, "right_input_hash": item.right_input_hash, "left_output_hash": item.left_output_hash, "right_output_hash": item.right_output_hash},
            first_divergent=item.first_divergent,
        ) for item in compared.stages]
        return compared.first_divergent_stage, output

    def add_decision(self, run_id: str, decision: ShadowReviewDecision) -> ShadowRunRecord:
        run = self._load(run_id)
        marker = "shadow-review:" + json.dumps(decision.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        self.canonical.save_run(run.with_note(marker))
        self.canonical.append_audit(run_id, {"kind": "review_decision", "decision": decision.model_dump(mode="json")})
        return self.read(run_id)

    def add_note(self, run_id: str, note: dict[str, str]) -> ShadowRunRecord:
        run = self._load(run_id)
        self.canonical.save_run(run.with_note(note.get("note", "")))
        self.canonical.append_audit(run_id, {"kind": "reviewer_note", "note": note, "at": utc_now()})
        return self.read(run_id)

    def review_decisions(self, run_id: str) -> list[ShadowReviewDecision]:
        run = self._load(run_id)
        output: list[ShadowReviewDecision] = []
        for note in run.reviewer_notes:
            if not note.startswith("shadow-review:"):
                continue
            try:
                output.append(ShadowReviewDecision.model_validate_json(note.removeprefix("shadow-review:")))
            except ValueError:
                continue
        return output

    def artifact_content(self, reference: ShadowArtifactReference) -> dict[str, Any] | None:
        try:
            value = self.canonical.read_artifact(reference.artifact_id.split(":", 1)[0], reference.stage)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def default_downstream() -> list[dict[str, Any]]:
        return [
            {"consumer": "chat/corrections", "status": "excluded", "reason": "shadow evidence is diagnostic-only", "executed": False},
            {"consumer": "plans/sessions", "status": "unchanged", "reason": "legacy authority retained", "executed": False},
            {"consumer": "growth/compare", "status": "incompatible", "reason": "cross-authority deltas require explicit review", "executed": False},
            {"consumer": "skills/XP", "status": "excluded", "reason": "shadow facts cannot unlock skills", "executed": False},
            {"consumer": "memories", "status": "excluded", "reason": "no shadow suggestions", "executed": False},
            {"consumer": "chapters/annual", "status": "unchanged", "reason": "no regeneration requested", "executed": False},
            {"consumer": "shares/exports/notifications", "status": "excluded", "reason": "shadow artifacts are not public", "executed": False},
        ]
