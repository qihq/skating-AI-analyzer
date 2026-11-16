"""Synthetic acquisition-control tests; never model inference or real TLS acceptance."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("acquire", Path(__file__).with_name("acquire-r1-official-model.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
PAYLOAD = b"PK\x03\x04" + b"synthetic-not-a-model" * 60000


class Response(io.BytesIO):
    status = 200
    url = "https://release-assets.githubusercontent.com/test/yolov8n.pt"
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}


class AcquisitionControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fetch(self, metadata_error=True, digest=None):
        output = self.root / "bundle"
        with patch.object(m.urllib.request, "build_opener") as mocked:
            metadata = {"tag_name": m.RELEASE, "assets": [{"name": "yolov8n.pt", "size": len(PAYLOAD), "browser_download_url": m.SOURCE, "digest": digest}]}
            first = TimeoutError("synthetic metadata timeout") if metadata_error else Response(json.dumps(metadata).encode())
            mocked.return_value.open.side_effect = [first, Response(PAYLOAD)]
            m.fetch(output, 1)
        return output

    def test_official_download_without_separate_digest_can_stage(self):
        bundle = self.fetch()
        source = json.loads((bundle / "model-source.json").read_text())
        self.assertIsNone(source["official_digest"])
        self.assertIn("no independently published hash", source["hash_basis"])
        release = self.root / "release"; release.mkdir()
        m.stage(bundle, release)
        self.assertEqual((release / "models/yolov8n.pt").read_bytes(), PAYLOAD)

    def test_official_digest_mismatch_leaves_no_verified_source(self):
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.fetch(False, "sha256:" + "0" * 64)
        self.assertFalse((self.root / "bundle/model-source.json").exists())
        self.assertEqual(json.loads((self.root / "bundle/acquisition-receipt.json").read_text())["status"], "failed")

    def test_official_digest_match_is_recorded(self):
        digest = "sha256:" + hashlib.sha256(PAYLOAD).hexdigest()
        bundle = self.fetch(False, digest)
        self.assertEqual(json.loads((bundle / "model-source.json").read_text())["official_digest"], digest)

    def test_modified_bundle_is_rejected_before_stage(self):
        bundle = self.fetch(); (bundle / "yolov8n.pt").write_bytes(b"corrupted")
        release = self.root / "release"; release.mkdir()
        with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
            m.stage(bundle, release)
        self.assertFalse((release / "model-source.json").exists())

    def test_published_release_is_immutable(self):
        bundle = self.fetch(); release = self.root / "release"; release.mkdir()
        (release / "manifest.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "immutable"):
            m.stage(bundle, release)

    def test_download_failure_preserves_failure_receipt(self):
        with patch.object(m.urllib.request, "build_opener") as mocked:
            mocked.return_value.open.side_effect = TimeoutError("synthetic network failure")
            with self.assertRaises(TimeoutError):
                m.fetch(self.root / "bundle", 1)
        self.assertEqual(json.loads((self.root / "bundle/acquisition-receipt.json").read_text())["status"], "failed")
        self.assertFalse((self.root / "bundle/model-source.json").exists())

    def test_redirects_reject_http_and_third_party(self):
        for url in ["http://github.com/file", "https://example.com/file", "https://github.com.evil.test/file", "https://user:password@github.com/file"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                m.check_url(url)
        m.check_url("https://release-assets.githubusercontent.com/file")

    def test_receipt_tamper_is_rejected(self):
        bundle = self.fetch(); (bundle / "acquisition-receipt.json").write_text("{}")
        release = self.root / "release"; release.mkdir()
        with self.assertRaises((ValueError, KeyError)):
            m.stage(bundle, release)


if __name__ == "__main__":
    unittest.main(verbosity=2)
