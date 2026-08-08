from __future__ import annotations

import importlib.util
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "ai_skating_analysis_pack"
SERVICES_DIR = REPO_ROOT / "backend" / "app" / "services"
PACK_SERVICES_DIR = PACK_DIR / "src" / "app" / "services"
V2_DIR = REPO_ROOT / "backend" / "app" / "analysis_v2"
PACK_V2_DIR = PACK_DIR / "src" / "app" / "analysis_v2"


def _load_script(name: str):
    path = PACK_DIR / name
    spec = importlib.util.spec_from_file_location(f"test_{name[:-3]}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _analysis_v2_imports(root: Path) -> set[str]:
    """Return absolute V2 module names imported by generated package files."""
    modules: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == "app.analysis_v2" or node.module.startswith("app.analysis_v2."):
                    modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.analysis_v2" or alias.name.startswith("app.analysis_v2."):
                        modules.add(alias.name)
    return modules


class AiPackGenerationTests(unittest.TestCase):
    def test_builders_target_repo_and_include_prompt_template(self) -> None:
        rebuild = _load_script("_rebuild.py")
        build_pack = _load_script("_build_pack.py")

        self.assertEqual(rebuild.REPO_ROOT, REPO_ROOT)
        self.assertEqual(rebuild.SRC, SERVICES_DIR)
        self.assertIn("vision_prompt_templates.py", rebuild.FILES)
        self.assertEqual(build_pack.REPO_ROOT, REPO_ROOT)
        self.assertIn("vision_prompt_templates.py", build_pack.AI_SERVICE_FILES)

    def test_rebuild_keeps_all_generated_services_in_sync(self) -> None:
        rebuild = _load_script("_rebuild.py")

        rebuild.main()

        for name in rebuild.FILES:
            self.assertEqual(
                (SERVICES_DIR / name).read_bytes(),
                (PACK_SERVICES_DIR / name).read_bytes(),
            )
        for name in rebuild.V2_FILES:
            self.assertEqual((V2_DIR / name).read_bytes(), (PACK_V2_DIR / name).read_bytes())

    def test_rebuild_declares_complete_top_level_v2_snapshot(self) -> None:
        rebuild = _load_script("_rebuild.py")

        expected = {path.name for path in V2_DIR.glob("*.py")}
        self.assertEqual(len(rebuild.V2_FILES), len(set(rebuild.V2_FILES)))
        self.assertEqual(set(rebuild.V2_FILES), expected)

    def test_generated_services_declare_every_v2_dependency(self) -> None:
        """The delivery snapshot must not omit a V2 module used by a service."""
        rebuild = _load_script("_rebuild.py")
        rebuild.main()

        imported = _analysis_v2_imports(PACK_SERVICES_DIR)
        declared = {f"app.analysis_v2.{name[:-3]}" for name in rebuild.V2_FILES if name.endswith(".py") and name != "__init__.py"}
        declared.add("app.analysis_v2")
        undeclared = sorted(imported - declared)
        self.assertEqual(undeclared, [], f"package services import undeclared V2 modules: {undeclared}")
        missing = sorted(
            module
            for module in imported
            if module != "app.analysis_v2"
            and not (PACK_V2_DIR.joinpath(*module.split(".")[2:]).with_suffix(".py")).exists()
        )
        self.assertEqual(missing, [], f"package snapshot is missing imported V2 files: {missing}")

    def test_generated_v2_snapshot_imports_in_clean_package_process(self) -> None:
        """Import every generated V2 module with only the package on PYTHONPATH."""
        rebuild = _load_script("_rebuild.py")
        rebuild.main()
        module_names = [
            f"app.analysis_v2.{name[:-3]}"
            for name in rebuild.V2_FILES
            if name.endswith(".py") and name != "__init__.py"
        ]
        script = (
            "import importlib\n"
            f"modules = {module_names!r}\n"
            "for module in modules:\n"
            "    importlib.import_module(module)\n"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACK_DIR / "src")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PACK_DIR),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"generated V2 snapshot failed clean import:\nstdout={result.stdout}\nstderr={result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
