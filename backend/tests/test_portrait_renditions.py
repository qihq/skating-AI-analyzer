"""Real-ffmpeg rendition sizing checks for A2-20261019 (portrait 720x1280 regression).

Requires the fixed module to be importable as ``app.services.media_renditions`` (install this
file in the repository test tree).  ffmpeg/ffprobe must be present; if either binary is
missing the checks are skipped with an explicit reason instead of failing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = next(
    (path for path in Path(__file__).resolve().parents if (path / "app" / "services" / "media_renditions.py").is_file()),
    Path(__file__).resolve().parents[1],
)
sys.path.insert(0, str(REPO_ROOT))

from app.services.media_renditions import generate_media_renditions  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
DISPLAY_RATIO_TOLERANCE = 0.005


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True)


def _make_clip(path: Path, width: int, height: int) -> Path:
    """Synthesize a 1s H.264/AAC clip with the requested pixel dimensions."""
    _run(
        [
            FFMPEG, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ]
    )
    return path


def _probe_video(path: Path) -> tuple[int, int, float]:
    """Return (width, height, sample aspect ratio) straight from the encoded file."""
    result = _run(
        [
            FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,sample_aspect_ratio",
            "-print_format", "json", str(path),
        ]
    )
    stream = json.loads(result.stdout)["streams"][0]
    numerator, _, denominator = str(stream.get("sample_aspect_ratio") or "1:1").partition(":")
    try:
        sar = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        sar = 1.0
    return int(stream["width"]), int(stream["height"]), sar or 1.0


def _display_ratio(size: tuple[int, int, float]) -> float:
    width, height, sar = size
    return width * sar / height


class PortraitRenditionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not FFMPEG or not FFPROBE:
            raise unittest.SkipTest("ffmpeg/ffprobe not installed: real rendition checks skipped")

    async def _render(self, width: int, height: int) -> tuple[dict[str, dict], Path, tuple[int, int, float]]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        video = _make_clip(base / "source.mp4", width, height)
        manifest = await generate_media_renditions(video, "analysis-rendition-sizes")
        self.assertEqual(manifest["status"], "ready")
        return {item["quality"]: item for item in manifest["sources"]}, base, _probe_video(video)

    def _assert_rendition(self, base: Path, item: dict, source: tuple[int, int, float], limit: int) -> None:
        self.assertEqual(item["status"], "ready", item.get("error"))
        size = _probe_video(base / str(item["filename"]))
        self.assertGreater(size[0], 0)
        self.assertGreater(size[1], 0)
        self.assertEqual(size[0] % 2, 0)
        self.assertEqual(size[1] % 2, 0)
        self.assertLessEqual(size[1], min(limit, source[1]))
        self.assertAlmostEqual(_display_ratio(size), _display_ratio(source), delta=DISPLAY_RATIO_TOLERANCE)

    async def test_portrait_source_renders_every_requested_quality(self) -> None:
        sources, base, source = await self._render(720, 1280)
        self.assertEqual([q for q in ("1080p", "720p", "480p") if q in sources], ["1080p", "720p", "480p"])
        for quality, limit in (("1080p", 1080), ("720p", 720), ("480p", 480)):
            self._assert_rendition(base, sources[quality], source, limit)
        self.assertEqual(sources["720p"]["height"], 720)

    async def test_landscape_source_skips_upscaled_quality(self) -> None:
        sources, base, source = await self._render(1280, 720)
        self.assertEqual(sorted(q for q in sources if q != "original"), ["480p"])
        self._assert_rendition(base, sources["480p"], source, 480)


if __name__ == "__main__":
    unittest.main()
