from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.media_renditions import (
    MEDIA_SCHEMA_VERSION,
    create_manifest,
    generate_media_renditions,
    manifest_path_for_video,
    read_or_create_manifest,
    resolve_media_source,
)


def _write_manifest(video: Path, sources: list[dict]) -> None:
    manifest_path_for_video(video).write_text(
        json.dumps({"schema_version": MEDIA_SCHEMA_VERSION, "status": "ready", "sources": sources}),
        encoding="utf-8",
    )


def _entry(quality: str, status: str, width: int, height: int, error: str | None = None) -> dict:
    entry = {
        "quality": quality,
        "status": status,
        "width": width,
        "height": height,
        "url": "x",
        "filename": "source.mp4" if quality == "original" else f"renditions/{quality}.mp4",
    }
    if error:
        entry["error"] = error
    return entry


def _persisted_sources(video: Path) -> dict[str, dict]:
    payload = json.loads(manifest_path_for_video(video).read_text(encoding="utf-8"))
    return {item["quality"]: item for item in payload["sources"]}


class MediaRenditionTests(unittest.IsolatedAsyncioTestCase):
    def test_manifest_skips_upscales_and_writes_legacy_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"source")
            metadata = {"width": 960, "height": 540, "codec": "h264", "duration_sec": 4.0, "bitrate": 1000}
            with patch("app.services.media_renditions._probe", return_value=metadata):
                manifest = read_or_create_manifest(video, "analysis-1")

        self.assertEqual(manifest["schema_version"], MEDIA_SCHEMA_VERSION)
        self.assertEqual([item["quality"] for item in manifest["sources"]], ["original", "480p"])
        self.assertTrue(manifest_path_for_video(video).name == "media-manifest.json")

    def test_resolve_source_stays_within_analysis_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            rendition = Path(tmp) / "renditions" / "720p.mp4"
            rendition.parent.mkdir()
            video.write_bytes(b"source")
            rendition.write_bytes(b"rendition")
            manifest_path_for_video(video).write_text(
                json.dumps(
                    {
                        "schema_version": MEDIA_SCHEMA_VERSION,
                        "status": "ready",
                        "sources": [
                            {"quality": "original", "status": "ready", "width": 1920, "height": 1080, "url": "x", "filename": "source.mp4"},
                            {"quality": "720p", "status": "ready", "width": 1280, "height": 720, "url": "x", "filename": "renditions/720p.mp4"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(resolve_media_source(video, "analysis-1", "original"), video)
            self.assertEqual(resolve_media_source(video, "analysis-1", "720p"), rendition.resolve())
            self.assertIsNone(resolve_media_source(video, "analysis-1", "480p"))

    async def test_renditions_record_partial_failure_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"source")
            source_metadata = {"width": 1920, "height": 1080, "codec": "h264", "duration_sec": 4.0, "bitrate": 1000}

            def fake_run(command: list[str], **_: object) -> object:
                target = Path(command[-1])
                if "720p" in str(target):
                    return type("Result", (), {"returncode": 1, "stderr": "encoder failed"})()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"rendition")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with (
                patch("app.services.media_renditions._probe", return_value=source_metadata),
                patch("app.services.media_renditions.subprocess.run", side_effect=fake_run),
            ):
                manifest = await generate_media_renditions(video, "analysis-1")

        by_quality = {item["quality"]: item for item in manifest["sources"]}
        self.assertNotIn("1080p", by_quality)
        self.assertEqual(by_quality["720p"]["status"], "failed")
        self.assertEqual(by_quality["480p"]["status"], "ready")
        self.assertEqual(manifest["status"], "ready")

    async def test_successful_retry_clears_previous_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"source")
            _write_manifest(video, [_entry("original", "ready", 720, 1280), _entry("720p", "failed", 720, 720, error="width not divisible by 2 (405x720)")])

            def fake_run(command: list[str], **_: object) -> object:
                target = Path(command[-1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"rendition")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            rendered = {"width": 406, "height": 720, "codec": "h264", "duration_sec": 1.0, "bitrate": 1000}
            with (
                patch("app.services.media_renditions._probe", return_value=rendered),
                patch("app.services.media_renditions.subprocess.run", side_effect=fake_run),
            ):
                manifest = await generate_media_renditions(video, "analysis-1")

            by_quality = {item["quality"]: item for item in manifest["sources"]}
            self.assertEqual(by_quality["720p"]["status"], "ready")
            self.assertEqual(by_quality["720p"]["width"], 406)
            self.assertNotIn("error", by_quality["720p"])
            self.assertNotIn("error", _persisted_sources(video)["720p"])

    async def test_ready_rendition_with_stale_error_is_cleaned_without_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"source")
            _write_manifest(video, [_entry("original", "ready", 720, 1280), _entry("720p", "ready", 406, 720, error="width not divisible by 2 (405x720)")])

            with patch("app.services.media_renditions.subprocess.run") as run:
                manifest = await generate_media_renditions(video, "analysis-1")

            run.assert_not_called()
            by_quality = {item["quality"]: item for item in manifest["sources"]}
            self.assertEqual(by_quality["720p"]["status"], "ready")
            self.assertNotIn("error", by_quality["720p"])
            self.assertNotIn("error", _persisted_sources(video)["720p"])

    async def test_repeated_failure_records_new_error_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"source")
            _write_manifest(video, [_entry("original", "ready", 720, 1280), _entry("720p", "failed", 720, 720, error="old 405x720 failure")])

            def fake_run(command: list[str], **_: object) -> object:
                return type("Result", (), {"returncode": 1, "stderr": "new encoder failure"})()

            with patch("app.services.media_renditions.subprocess.run", side_effect=fake_run):
                manifest = await generate_media_renditions(video, "analysis-1")

            by_quality = {item["quality"]: item for item in manifest["sources"]}
            self.assertEqual(by_quality["720p"]["status"], "failed")
            self.assertIn("new encoder failure", by_quality["720p"]["error"])
            self.assertNotIn("old 405x720 failure", by_quality["720p"]["error"])
            self.assertIn("new encoder failure", _persisted_sources(video)["720p"]["error"])


if __name__ == "__main__":
    unittest.main()
