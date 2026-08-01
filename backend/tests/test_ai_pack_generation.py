from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
