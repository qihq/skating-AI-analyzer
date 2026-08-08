from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class RunManifest:
    source_identity: Mapping[str, str]
    pipeline_fingerprint: str
    stage_hashes: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_identity", MappingProxyType(dict(self.source_identity)))
        object.__setattr__(self, "stage_hashes", MappingProxyType({k: MappingProxyType(dict(v)) for k, v in self.stage_hashes.items()}))

    @classmethod
    def create(cls, *, source_identity: Mapping[str, str], pipeline_fingerprint: str) -> "RunManifest":
        if not source_identity or not pipeline_fingerprint:
            raise ValueError("source identity and pipeline fingerprint are required")
        return cls(source_identity, pipeline_fingerprint)

    def with_stage_hashes(self, stage: str, *, input_hash: str, output_hash: str) -> "RunManifest":
        if not stage or not input_hash or not output_hash:
            raise ValueError("stage and hashes are required")
        hashes = {k: dict(v) for k, v in self.stage_hashes.items()}
        hashes[stage] = {"input_hash": input_hash, "output_hash": output_hash}
        return RunManifest(self.source_identity, self.pipeline_fingerprint, hashes)

    def persist(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"source_identity": dict(self.source_identity), "pipeline_fingerprint": self.pipeline_fingerprint, "stage_hashes": {k: dict(v) for k, v in self.stage_hashes.items()}}
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @classmethod
    def load(cls, path: Path) -> "RunManifest":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload["source_identity"], payload["pipeline_fingerprint"], payload.get("stage_hashes", {}))
