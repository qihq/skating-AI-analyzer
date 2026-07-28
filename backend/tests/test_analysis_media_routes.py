from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.routers.analysis import get_analysis_media, get_analysis_video


class AnalysisMediaRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_rejects_unknown_quality_before_lookup(self) -> None:
        with self.assertRaises(HTTPException) as context:
            await get_analysis_video("missing", quality="4k", session=SimpleNamespace())
        self.assertEqual(context.exception.status_code, 422)

    async def test_media_uses_original_only_manifest_for_legacy_analysis(self) -> None:
        video = Path("C:/legacy/source.mp4")
        analysis = SimpleNamespace(id="legacy", video_path=str(video))
        session = SimpleNamespace(get=AsyncMock(return_value=analysis))
        manifest = {
            "schema_version": "analysis_media.v1",
            "status": "ready",
            "sources": [{"quality": "original", "status": "ready", "width": 640, "height": 360, "url": "/api/analysis/legacy/video?quality=original", "filename": "source.mp4"}],
        }
        with (
            patch("app.routers.analysis._safe_video_response_path", return_value=video),
            patch("app.routers.analysis.read_or_create_manifest", return_value=manifest),
        ):
            result = await get_analysis_media("legacy", session=session)

        self.assertEqual(result.sources[0].quality, "original")
