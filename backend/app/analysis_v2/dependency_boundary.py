"""Static guardrails for migrated backend analysis consumers.

The legacy presenter and prediction adapter are intentionally the only places
inside the V2 package allowed to inspect raw legacy analysis fields. New
downstream consumers must receive an ``AnalysisFactsV2`` projection instead.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


FORBIDDEN_LEGACY_FIELDS = (
    "bio_data",
    "vision_path_a",
    "vision_path_b",
    "pose_data",
)


def audit_migrated_modules(
    modules: Iterable[Path],
    *,
    exceptions: Iterable[Path] = (),
) -> tuple[tuple[str, str], ...]:
    """Return ``(module, field)`` violations for a bounded module set.

    Exceptions are exact paths, not filename/glob matches, so the legacy
    adapter escape hatch cannot silently expand to unrelated services.
    """

    paths = tuple(Path(path) for path in modules)
    allowed = {path.resolve() for path in exceptions}
    supplied = {path.resolve() for path in paths}
    unknown = allowed - supplied
    if unknown:
        raise ValueError("legacy adapter exception must reference an audited module")

    violations: list[tuple[str, str]] = []
    for path in paths:
        if path.resolve() in allowed or path.suffix != ".py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_LEGACY_FIELDS:
                violations.append((str(path), node.attr))
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                if node.slice.value in FORBIDDEN_LEGACY_FIELDS:
                    violations.append((str(path), node.slice.value))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in FORBIDDEN_LEGACY_FIELDS
            ):
                violations.append((str(path), node.args[0].value))
    return tuple(sorted(violations))
