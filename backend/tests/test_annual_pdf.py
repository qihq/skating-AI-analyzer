from __future__ import annotations

import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


def _annual_pdf_module():
    module_path = Path(__file__).resolve().parents[1] / "app" / "services" / "annual_pdf.py"
    spec = spec_from_file_location("annual_pdf_under_test", module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AnnualPdfTests(unittest.TestCase):
    def test_renderer_writes_extractable_chinese_text_and_text_only_fallback(self) -> None:
        render_annual_pdf = _annual_pdf_module().render_annual_pdf

        snapshot = {
            "schema_version": "annual_collection.v1",
            "skater_id": "skater-1",
            "year": 2026,
            "chapters": [
                {
                    "id": "chapter-1",
                    "year_month": "2026-01",
                    "revision": 1,
                    "final_text": "一月的成长记录：她完成了稳定的起跳练习。",
                    "coverage": {"sessions": 2, "completed_analyses": 3, "comparable_metrics": 1},
                    "quote_facts": [{"id": "quote-1", "text": "我还想再试一次", "speaker": "skater"}],
                    "representative_frames": [],
                    "media_mode": "text_only",
                },
            ],
            "milestones": [
                {"id": "milestone-1", "title": "华尔兹跳", "occurred_at": "2026-01-21T00:00:00+00:00", "verification": "parent_confirmed", "note": "连续三次落冰"},
            ],
            "coverage": {"published_chapter_count": 1, "text_only_chapter_count": 1, "selected_milestone_count": 1},
            "metric_definitions": {"completed_analyses": "已完成的视频分析次数。"},
        }
        font_paths = {"regular": Path("C:/Windows/Fonts/Deng.ttf"), "bold": Path("C:/Windows/Fonts/Dengb.ttf")}
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "annual.pdf"
            result = render_annual_pdf(snapshot, output_path, font_paths)
            payload = output_path.read_bytes()

        self.assertTrue(payload.startswith(b"%PDF"))
        self.assertGreaterEqual(result.page_count, 5)
        self.assertEqual(len(result.file_sha256), 64)
        self.assertIn("一月的成长记录", result.extracted_text)
        self.assertIn("本章节没有可用于导出的代表图片", result.extracted_text)
        self.assertIn("第 1 页", result.extracted_text)

    def test_renderer_rejects_missing_font_paths(self) -> None:
        module = _annual_pdf_module()
        AnnualPdfFontError = module.AnnualPdfFontError
        render_annual_pdf = module.render_annual_pdf

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AnnualPdfFontError):
                render_annual_pdf(
                    {"year": 2026, "chapters": [], "milestones": [], "coverage": {}, "metric_definitions": {}},
                    Path(directory) / "annual.pdf",
                    {"regular": Path(directory) / "missing.ttf", "bold": Path(directory) / "missing-bold.ttf"},
                )

    def test_renderer_uses_allowlisted_frame_and_falls_back_when_frame_is_missing(self) -> None:
        module = _annual_pdf_module()
        render_annual_pdf = module.render_annual_pdf
        from PIL import Image

        snapshot = {
            "year": 2026,
            "chapters": [{
                "year_month": "2026-01", "final_text": "Frame chapter", "coverage": {}, "quote_facts": [],
                "media_mode": "with_frames",
                "representative_frames": [
                    {"analysis_id": "analysis-1", "frame_id": "frame_0001", "phase": "landing"},
                    {"analysis_id": "../escape", "frame_id": "frame_0002", "phase": "takeoff"},
                ],
            }],
            "milestones": [], "coverage": {}, "metric_definitions": {},
        }
        font_paths = {"regular": Path("C:/Windows/Fonts/Deng.ttf"), "bold": Path("C:/Windows/Fonts/Dengb.ttf")}
        with tempfile.TemporaryDirectory() as directory:
            uploads = Path(directory) / "uploads"
            source = uploads / "analysis-1" / "frames" / "frame_0001.jpg"
            source.parent.mkdir(parents=True)
            Image.new("RGB", (3000, 1200), "navy").save(source)
            output_path = Path(directory) / "annual.pdf"
            result = render_annual_pdf(snapshot, output_path, font_paths, frames_root=uploads)

        self.assertIn("Representative frame: landing", result.extracted_text)
        self.assertIn("Representative frame unavailable: takeoff", result.extracted_text)


if __name__ == "__main__":
    unittest.main()
