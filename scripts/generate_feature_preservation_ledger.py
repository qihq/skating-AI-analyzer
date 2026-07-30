from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "feature-preservation" / "ledger.json"
ALLOWED_STATUSES = ["inventoried", "characterized", "adapted", "verified", "retirement-approved"]


def _source(path: Path, line: int = 1) -> str:
    return f"{path.relative_to(ROOT).as_posix()}:{line}"


def _owner(kind: str, name: str) -> int:
    lowered = name.lower()
    if "evaluator" in lowered or "pilot" in lowered or "review-attestations" in lowered:
        return 3
    if kind in {"environment_setting", "package_entrypoint", "startup_or_scheduled_job"}:
        return 0 if not any(term in lowered for term in ("v2", "shadow", "golden")) else 15
    if kind == "database_model":
        return 14 if any(term in lowered for term in ("analysis", "plan", "skill", "memory", "chapter", "annual")) else 0
    rules = [
        ("golden", 1), ("debug", 7), ("target", 8), ("pose", 9), ("compare", 14),
        ("chat", 14), ("correction", 14), ("plan", 14), ("growth", 14), ("skill", 14),
        ("snowball", 14), ("memory", 14), ("chapter", 14), ("annual", 14), ("export", 14),
        ("provider", 14), ("backup", 16), ("storage", 16), ("system", 16),
    ]
    return next((iteration for term, iteration in rules if term in lowered), 5 if kind.startswith("frontend") else 17)


def _permissions(text: str) -> str:
    lowered = text.lower()
    if "x-parent-pin" in lowered or "require_parent" in lowered or "parent" in lowered:
        return "parent-authorized or parent-aware; preserve current backend and UI checks"
    return "current family access; must not become more permissive during migration"


def _fixture(name: str, tests: list[str]) -> str:
    tokens = {token for token in re.split(r"[^a-z0-9]+", name.lower()) if len(token) >= 4}
    candidates = [test for test in tests if any(token in test.lower() for token in tokens)]
    return candidates[0] if candidates else "new characterization task required by owning iteration"


def _entry(
    *, kind: str, name: str, source: str, read: str, write: str, permissions: str,
    artifact: str, tests: list[str], detail: str = "",
) -> dict[str, Any]:
    entry_id = f"{kind}:{name}"
    owner = _owner(kind, name)
    return {
        "id": entry_id,
        "kind": kind,
        "name": name,
        "source": source,
        "owning_iteration": owner,
        "current_reads": read,
        "current_writes": write,
        "permissions": permissions,
        "data_and_artifacts": artifact,
        "legacy_fixture": _fixture(name, tests),
        "v2_fixture": f"Iteration {owner} contract fixture; legacy behavior remains characterized until adapted",
        "shadow_behavior": "must not create or mutate family rows or artifacts; diagnostic-only if applicable",
        "restart_behavior": "preserve current behavior and verify persistence or idempotence in owning iteration",
        "backup_restore_behavior": "durable state included; rebuildable data explicitly documented and safe to omit",
        "rollback_behavior": "complete legacy behavior and historical data remain readable after rollback",
        "migration_status": "inventoried",
        "detail": detail,
    }


def _python_routes(tests: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        prefixes: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if getattr(node.value.func, "id", None) == "APIRouter":
                    prefix = next((kw.value.value for kw in node.value.keywords if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)), "")
                    for target in node.targets:
                        if isinstance(target, ast.Name): prefixes[target.id] = prefix
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            segment = ast.get_source_segment(text, node) or ""
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute): continue
                method = decorator.func.attr.upper()
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}: continue
                route = decorator.args[0].value if decorator.args and isinstance(decorator.args[0], ast.Constant) else ""
                prefix = prefixes.get(getattr(decorator.func.value, "id", ""), "")
                name = f"{method} {prefix}{route}"
                entries.append(_entry(
                    kind="backend_route", name=name, source=_source(path, node.lineno),
                    read="request parameters, authorized database/service state",
                    write="none" if method == "GET" else f"{method} mutation and its current side effects",
                    permissions=_permissions(segment), artifact="route response and any existing generated files",
                    tests=tests, detail=node.name,
                ))
    return entries


def _frontend_routes(tests: list[str]) -> list[dict[str, Any]]:
    path = ROOT / "frontend" / "src" / "App.tsx"
    text = path.read_text(encoding="utf-8")
    entries = []
    for match in re.finditer(r'<Route\s+path="([^"]+)"', text):
        route = match.group(1)
        line = text.count("\n", 0, match.start()) + 1
        entries.append(_entry(
            kind="frontend_route", name=route, source=_source(path, line),
            read="route state and current backend API contracts", write="user actions delegated to typed API client",
            permissions=_permissions(text[match.start():match.start() + 400]), artifact="browser route and historical deep-link semantics",
            tests=tests,
        ))
    return entries


def _frontend_api(tests: list[str]) -> list[dict[str, Any]]:
    pattern = re.compile(r"export\s+(?:async\s+)?(?:function|const)\s+([A-Za-z0-9_]+)")
    entries = []
    for path in [ROOT / "frontend" / "src" / "api" / "client.ts", ROOT / "frontend" / "src" / "analysis-v2" / "api.ts"]:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            body = text[match.start():match.start() + 900]
            method_match = re.search(r"apiClient\.(get|post|put|patch|delete)", body)
            method = method_match.group(1).upper() if method_match else "TRANSPORT"
            entries.append(_entry(
                kind="frontend_api_operation", name=name, source=_source(path, line),
                read=f"typed {method} API response", write="none" if method in {"GET", "TRANSPORT"} else f"{method} request mutation",
                permissions=_permissions(body), artifact="frontend API contract and cache-visible response", tests=tests, detail=method,
            ))
    return entries


def _models(tests: list[str]) -> list[dict[str, Any]]:
    path = ROOT / "backend" / "app" / "models.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    entries = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef): continue
        table = next((item.value.value for item in node.body if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in item.targets) and isinstance(item.value, ast.Constant)), None)
        if table:
            entries.append(_entry(
                kind="database_model", name=f"{node.name}:{table}", source=_source(path, node.lineno),
                read="ORM queries and historical snapshot reads", write="existing CRUD, revisions, status transitions, and relationships",
                permissions="enforced by owning routers/services", artifact=f"durable database table {table}", tests=tests,
            ))
    return entries


def _environment(tests: list[str]) -> list[dict[str, Any]]:
    found: dict[str, tuple[Path, int]] = {}
    pattern = re.compile(r'(?:os\.getenv|os\.environ\.get)\(\s*["\']([A-Z][A-Z0-9_]*)["\']')
    for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            found.setdefault(match.group(1), (path, text.count("\n", 0, match.start()) + 1))
    for path in [ROOT / ".env.example", ROOT / "docker-compose.yml"]:
        if not path.exists(): continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)\s*[=:]", text):
            found.setdefault(match.group(1), (path, text.count("\n", 0, match.start()) + 1))
    return [_entry(
        kind="environment_setting", name=name, source=_source(path, line),
        read="process environment or deployment configuration", write="runtime configuration only; no implicit user-data mutation",
        permissions="parent/operator configuration; secrets must remain redacted", artifact="configuration/model/provider fingerprint input",
        tests=tests,
    ) for name, (path, line) in sorted(found.items())]


def _jobs(tests: list[str]) -> list[dict[str, Any]]:
    path = ROOT / "backend" / "app" / "main.py"
    text = path.read_text(encoding="utf-8")
    names = ["init_db", "backfill_applied_analysis_corrections", "recover_incomplete_exports", "seed_preset_skaters", "seed_default_memories", "seed_skill_catalog", "sync_all_skater_progress", "archive_policy", "annual_export_task_shutdown"]
    return [_entry(
        kind="startup_or_scheduled_job", name=name, source=_source(path, next((i for i, line in enumerate(text.splitlines(), 1) if name.split("_")[0] in line), 1)),
        read="database, settings, or durable job state", write="idempotent startup/scheduled/recovery behavior",
        permissions="system startup or scheduler", artifact="database rows, archive/annual artifacts, logs or task state", tests=tests,
    ) for name in names]


def _manual_entries(tests: list[str]) -> list[dict[str, Any]]:
    durable = {
        "source_videos": "uploads and archive; durable/private", "analyses": "database plus analysis media; durable",
        "chat_and_corrections": "database; durable immutable history", "plans_and_sessions": "database and shares; durable",
        "skills_and_progress": "database; durable", "memories": "database; durable", "monthly_chapters": "database; durable",
        "annual_collections_and_exports": "database and PDFs; durable", "golden_labels": "private V2 runtime; durable, never Git",
        "v2_artifacts": "private V2 runtime; rebuildable until explicitly published", "caches": "runtime cache; rebuildable",
        "model_files": "mounted/local models; operational, backed up by deployment policy", "provider_secrets": "encrypted database fields; durable/secret",
        "ui_preferences": "database/local browser state; durable according to current scope",
    }
    entries = [_entry(
        kind="durable_data", name=name, source="docs/feature-preservation/data-inventory.md:1",
        read="current services and UI", write="current explicit workflow only", permissions="preserve existing family/parent/operator boundary",
        artifact=description, tests=tests,
    ) for name, description in durable.items()]
    artifacts = ["analysis_media_and_renditions", "analysis_text_export", "chat_share", "plan_share", "milestone_share_image", "monthly_representative_media", "annual_pdf", "backup_archive", "debug_and_golden_outputs"]
    entries.extend(_entry(
        kind="generated_artifact", name=name, source="docs/feature-preservation/data-inventory.md:1",
        read="existing URLs/downloads and historical snapshots", write="existing explicit generation/revision workflow",
        permissions="preserve current authorization and private/public boundary", artifact=name, tests=tests,
    ) for name in artifacts)
    package_paths = ["backend/Dockerfile", "frontend/Dockerfile", "docker/allinone/Dockerfile", "docker/allinone/start.sh", "docker-compose.yml", "ai_skating_analysis_pack", "scripts/export-allinone-image.ps1"]
    entries.extend(_entry(
        kind="package_entrypoint", name=name, source=f"{name}:1", read="source, dependencies, models and deployment environment",
        write="build/runtime outputs only", permissions="operator/deployment boundary", artifact="Docker/all-in-one/standalone package", tests=tests,
    ) for name in package_paths)
    return entries


def generate_ledger() -> dict[str, Any]:
    tests = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "backend" / "tests").rglob("test_*.py"))
    tests += sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "frontend" / "src").rglob("*.test.ts*"))
    entries: list[dict[str, Any]] = []
    entries.extend(_python_routes(tests))
    entries.extend(_frontend_routes(tests))
    entries.extend(_frontend_api(tests))
    entries.extend(_models(tests))
    entries.extend(_jobs(tests))
    entries.extend(_environment(tests))
    entries.extend(_manual_entries(tests))
    entries.extend(_entry(
        kind="focused_test", name=test, source=f"{test}:1", read="fixture and production behavior under test",
        write="isolated temporary test state only", permissions="test boundary", artifact="characterization and regression evidence",
        tests=[test],
    ) for test in tests)
    entries.sort(key=lambda item: item["id"])
    ids = [entry["id"] for entry in entries]
    fingerprint = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    return {
        "schema_version": "feature-preservation.v1",
        "baseline_commit": "c291324c62bcc930f96f3429dcdc9521e060b516",
        "allowed_statuses": ALLOWED_STATUSES,
        "retirement_policy": "retirement-approved requires explicit owner approval; no Iteration 0 entry may use it",
        "inventory_fingerprint": fingerprint,
        "entry_count": len(entries),
        "entries": entries,
    }


if __name__ == "__main__":
    ledger = generate_ledger()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {ledger['entry_count']} entries to {OUTPUT.relative_to(ROOT)}")
