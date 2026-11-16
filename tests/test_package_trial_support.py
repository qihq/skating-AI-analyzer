#!/usr/bin/env python3
"""Targeted tests for the R1.2-P1 trial-support packager.

Run directly::

    python3 output/tests/test_package_trial_support.py

or via discovery::

    python3 -m unittest discover -s output/tests -v

No network, no shell and no real ~900 MB tar: every test builds a small
synthetic release directory in a temporary directory.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import package_trial_support as pts  # noqa: E402  (import after sys.path fix)

TAR_NAME = "trial-image r1-2 linux-amd64.tar"  # a space on purpose: GNU format must survive it
TAR_BYTES = b"synthetic tar payload for packaging tests\n" * 4
TAR_SHA256 = hashlib.sha256(TAR_BYTES).hexdigest()

EXPECTED_PAYLOAD = {
    "compose.r1-2.yml",
    "r1-2.env.example",
    "synthetic-no-person.mp4",
    "invalid-upload-fixture.mp4",
    "nas-feedback-template.json",
    "nas-trial-checklist.md",
    "image-manifest.original.json",
    "NAS-TRIAL-INSTALL.md",
    TAR_NAME + ".sha256",
}
EXPECTED_EXCLUDED = {"packaging-manifest.json", "trial-support.zip", "trial-support.zip.sha256"}

# Stale files that exist in the original release directory but must never be
# copied into the new package (they carry old digests / old line endings).
DECOY_FILES = {
    "artifact-manifest.json": b'{"stale": true}\n',
    "trial-support.zip": b"old zip bytes\r\n",
    "trial-support.zip.sha256": b"0" * 64 + b"  trial-support.zip\r\n",
    TAR_NAME + ".sha256": b"f" * 64 + b"  " + TAR_NAME.encode("ascii") + b"\r\n",
}


class PackagerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="r12-p1-package-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

        self.release = self.root / "release"
        self.release.mkdir()
        self.tar = self.release / TAR_NAME
        self.tar.write_bytes(TAR_BYTES)
        self.manifest = {
            "tar": TAR_NAME,
            "tar_bytes": len(TAR_BYTES),
            "tar_sha256": TAR_SHA256,
            "tag": "skating-analyzer-v2:trial-20261016-r1-2-3ebc4e2a",
            "image_id": "sha256:" + "1" * 64,
            "config_digest": "sha256:" + "2" * 64,
            "platform": "linux/amd64",
            "release": "R1.2 restricted legacy-analysis-preview",
            "date": "2026-10-16",
            "registry_pushed": False,
            "registry_published_digest": None,
            "target_nas_verified": False,
        }
        self.write_manifest()
        for name in (
            "compose.r1-2.yml",
            "r1-2.env.example",
            "synthetic-no-person.mp4",
            "invalid-upload-fixture.mp4",
            "nas-feedback-template.json",
            "nas-trial-checklist.md",
        ):
            (self.release / name).write_bytes("fixture bytes for {0}\n".format(name).encode("utf-8"))

        self.guide = self.root / "NAS-TRIAL-INSTALL.md"
        self.guide.write_bytes("# 安装说明（测试草稿）\n\n纯 LF 文本\n".encode("utf-8"))
        self.out = self.root / "package-out"

    # -- helpers ----------------------------------------------------------

    def write_manifest(self):
        (self.release / "manifest.json").write_bytes(
            (json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )

    def build(self, **overrides):
        kwargs = {"release_dir": self.release, "output_dir": self.out, "install_guide": self.guide}
        kwargs.update(overrides)
        return pts.build_package(**kwargs)

    def snapshot(self, directory):
        directory = Path(directory)
        state = {}
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                stat = path.stat()
                state[str(path.relative_to(directory))] = (
                    stat.st_size,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    stat.st_mtime_ns,
                )
        return state

    def read_packaging_manifest(self):
        return json.loads((self.out / "packaging-manifest.json").read_bytes().decode("utf-8"))

    def zip_names(self):
        with zipfile.ZipFile(self.out / "trial-support.zip") as archive:
            return archive.namelist()

    # -- newline / checksum format ---------------------------------------

    def test_checksum_files_are_lf_ascii_without_bom(self):
        self.build()

        tar_sidecar = self.out / (TAR_NAME + ".sha256")
        raw = tar_sidecar.read_bytes()
        expected = "{0}  {1}\n".format(TAR_SHA256, TAR_NAME).encode("ascii")
        self.assertEqual(raw, expected)
        self.assertNotIn(b"\r", raw)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\n"), 1)

        zip_raw = (self.out / "trial-support.zip.sha256").read_bytes()
        zip_digest = hashlib.sha256((self.out / "trial-support.zip").read_bytes()).hexdigest()
        self.assertEqual(zip_raw, "{0}  trial-support.zip\n".format(zip_digest).encode("ascii"))
        self.assertNotIn(b"\r", zip_raw)
        self.assertFalse(zip_raw.startswith(b"\xef\xbb\xbf"))

        with zipfile.ZipFile(self.out / "trial-support.zip") as archive:
            self.assertEqual(archive.read(TAR_NAME + ".sha256"), raw)
            manifest_inside = archive.read("packaging-manifest.json")
        self.assertNotIn(b"\r", manifest_inside)
        self.assertFalse(manifest_inside.startswith(b"\xef\xbb\xbf"))

    def test_gnu_sha256sum_format_matches_real_digest_and_space_basename(self):
        self.build()

        line = (self.out / (TAR_NAME + ".sha256")).read_bytes().decode("ascii")
        self.assertTrue(line.endswith("\n"))
        parts = line[:-1].split("  ")
        self.assertEqual(len(parts), 2)
        digest, name = parts
        self.assertEqual(digest, hashlib.sha256(self.tar.read_bytes()).hexdigest())
        self.assertEqual(name, TAR_NAME)
        self.assertIn(" ", TAR_NAME)
        self.assertEqual(Path(name).name, name)

        zip_line = (self.out / "trial-support.zip.sha256").read_bytes().decode("ascii")
        zip_digest, zip_name = zip_line[:-1].split("  ")
        self.assertEqual(zip_name, "trial-support.zip")
        self.assertEqual(zip_digest, hashlib.sha256((self.out / "trial-support.zip").read_bytes()).hexdigest())

    # -- zip content / manifest accuracy ---------------------------------

    def test_zip_contains_every_payload_and_no_tar_or_self_reference(self):
        self.build()
        packaging = self.read_packaging_manifest()
        declared = {record["path"] for record in packaging["payload_files"]}

        self.assertEqual(declared, EXPECTED_PAYLOAD)
        names = self.zip_names()
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), declared | {"packaging-manifest.json"})
        self.assertNotIn(TAR_NAME, names)
        self.assertEqual([name for name in names if name.endswith(".tar")], [])
        for excluded in EXPECTED_EXCLUDED:
            self.assertNotIn(excluded, declared)
        self.assertEqual(set(packaging["excluded_from_payload"]), EXPECTED_EXCLUDED)

    def test_payload_records_match_root_files_and_zip_entries(self):
        self.build()
        packaging = self.read_packaging_manifest()
        records = {record["path"]: record for record in packaging["payload_files"]}
        self.assertEqual(len(records), len(packaging["payload_files"]))

        with zipfile.ZipFile(self.out / "trial-support.zip") as archive:
            for name, record in records.items():
                root_bytes = (self.out / name).read_bytes()
                self.assertEqual(record["bytes"], len(root_bytes), name)
                self.assertEqual(record["sha256"], hashlib.sha256(root_bytes).hexdigest(), name)
                self.assertEqual(archive.read(name), root_bytes, name)

        self.assertEqual(
            records["image-manifest.original.json"]["sha256"],
            hashlib.sha256((self.release / "manifest.json").read_bytes()).hexdigest(),
        )

    def test_output_root_contains_payloads_manifest_and_zip_only(self):
        self.build()
        packaging = self.read_packaging_manifest()
        declared = {record["path"] for record in packaging["payload_files"]}

        root_files = {path.name for path in self.out.iterdir() if path.is_file()}
        self.assertEqual(
            root_files,
            declared | {"packaging-manifest.json", "trial-support.zip", "trial-support.zip.sha256"},
        )
        self.assertEqual([path.name for path in self.out.iterdir() if path.is_dir()], [])

    def test_packaging_manifest_marks_revision_and_tar_transport(self):
        self.build()
        packaging = self.read_packaging_manifest()

        self.assertEqual(packaging["package_revision"], "R1.2-P1")
        self.assertNotEqual(packaging["package_revision"], self.manifest["tag"])
        self.assertEqual(packaging["image_identity"]["tag"], self.manifest["tag"])
        self.assertEqual(packaging["image_identity"]["tar"], TAR_NAME)
        self.assertEqual(packaging["image_identity"]["tar_bytes"], len(TAR_BYTES))
        self.assertEqual(packaging["image_identity"]["tar_sha256"], TAR_SHA256)
        self.assertFalse(packaging["tar_transport"]["included_in_zip"])
        self.assertTrue(packaging["tar_transport"]["must_be_taken_from_original_package"])
        self.assertEqual(packaging["tar_transport"]["expected_sha256"], TAR_SHA256)
        original_manifest = packaging["original_manifest"]
        self.assertFalse(original_manifest["target_nas_verified_in_original_manifest"])
        self.assertNotIn("target_nas_verified_at_packaging", original_manifest)

    def test_original_manifest_is_renamed_with_original_bytes(self):
        self.build()
        original = (self.release / "manifest.json").read_bytes()
        copied = (self.out / "image-manifest.original.json").read_bytes()
        self.assertEqual(copied, original)
        self.assertFalse(json.loads(copied.decode("utf-8"))["target_nas_verified"])
        self.assertEqual(
            self.read_packaging_manifest()["original_manifest"]["sha256"],
            hashlib.sha256(original).hexdigest(),
        )

    # -- source immutability ---------------------------------------------

    def test_source_release_directory_is_unchanged(self):
        before = self.snapshot(self.release)
        guide_before = hashlib.sha256(self.guide.read_bytes()).hexdigest()

        self.build()

        self.assertEqual(self.snapshot(self.release), before)
        self.assertEqual(hashlib.sha256(self.guide.read_bytes()).hexdigest(), guide_before)

    # -- refusal paths ----------------------------------------------------

    def test_existing_output_directory_is_rejected_and_left_untouched(self):
        self.out.mkdir()
        sentinel = self.out / "keep.txt"
        sentinel.write_bytes(b"do not touch\n")
        before = self.snapshot(self.out)

        with self.assertRaises(pts.PackageError):
            self.build()

        self.assertEqual(self.snapshot(self.out), before)
        self.assertEqual(sentinel.read_bytes(), b"do not touch\n")
        self.assertFalse((self.out / "trial-support.zip").exists())

    def test_failed_build_keeps_incomplete_marker_and_no_final_sidecar(self):
        before = self.snapshot(self.release)

        with mock.patch.object(pts, "verify_output", side_effect=pts.PackageError("simulated failure")):
            with self.assertRaises(pts.PackageError):
                self.build()

        # The failed directory is kept as evidence, clearly marked INCOMPLETE,
        # and can never be mistaken for a verified package.
        self.assertTrue(self.out.is_dir())
        marker = self.out / "INCOMPLETE"
        self.assertEqual(marker.read_bytes(), pts.INCOMPLETE_TEXT)
        self.assertNotIn(b"\r", marker.read_bytes())
        self.assertFalse((self.out / "trial-support.zip.sha256").exists())
        self.assertTrue((self.out / "trial-support.zip").is_file())
        self.assertEqual(self.snapshot(self.release), before)

        with self.assertRaises(pts.PackageError):
            self.build()

    def test_wrong_tar_sha256_or_size_is_rejected_without_output(self):
        for field, value in (("tar_sha256", "0" * 64), ("tar_bytes", len(TAR_BYTES) + 1)):
            with self.subTest(field=field):
                self.manifest = dict(self.manifest)
                self.manifest[field] = value
                self.write_manifest()
                with self.assertRaises(pts.PackageError):
                    self.build()
                self.assertFalse(self.out.exists())

    def test_unsafe_tar_names_are_rejected_without_output(self):
        for name in ("../evil.tar", "sub/evil.tar", "sub\\evil.tar", "C:\\evil.tar", "/abs/evil.tar", "", "."):
            with self.subTest(name=name):
                self.manifest["tar"] = name
                self.write_manifest()
                with self.assertRaises(pts.PackageError):
                    self.build()
                self.assertFalse(self.out.exists())

    def test_missing_tar_file_is_rejected_without_output(self):
        self.manifest["tar"] = "missing-image.tar"
        self.write_manifest()

        with self.assertRaises(pts.PackageError):
            self.build()
        self.assertFalse(self.out.exists())

    def test_missing_required_input_yields_no_package(self):
        (self.release / "nas-trial-checklist.md").unlink()

        with self.assertRaises(pts.PackageError):
            self.build()

        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.rglob("trial-support.zip")), [])
        self.assertEqual(list(self.root.rglob("packaging-manifest.json")), [])

    def test_stale_artifacts_are_not_copied_into_the_package(self):
        for name, data in DECOY_FILES.items():
            (self.release / name).write_bytes(data)

        self.build()

        self.assertFalse((self.out / "artifact-manifest.json").exists())
        self.assertNotEqual(
            (self.out / "trial-support.zip").read_bytes(), DECOY_FILES["trial-support.zip"]
        )
        self.assertNotEqual(
            (self.out / "trial-support.zip.sha256").read_bytes(),
            DECOY_FILES["trial-support.zip.sha256"],
        )
        regenerated = (self.out / (TAR_NAME + ".sha256")).read_bytes()
        self.assertNotEqual(regenerated, DECOY_FILES[TAR_NAME + ".sha256"])
        self.assertNotIn(b"\r", regenerated)

        names = set(self.zip_names())
        for stale in ("artifact-manifest.json", "trial-support.zip", "trial-support.zip.sha256"):
            self.assertNotIn(stale, names)

    # -- CLI contract -----------------------------------------------------

    def test_cli_returns_zero_on_success_and_one_on_existing_output(self):
        argv = [
            "--release-dir",
            str(self.release),
            "--output-dir",
            str(self.out),
            "--install-guide",
            str(self.guide),
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            first_code = pts.main(argv)

        self.assertEqual(first_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        summary = json.loads(stdout.getvalue())
        self.assertEqual(summary["package_revision"], "R1.2-P1")
        self.assertEqual(summary["tar_sha256"], TAR_SHA256)
        self.assertFalse(summary["tar_included_in_zip"])
        self.assertTrue((self.out / "trial-support.zip").is_file())

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            second_code = pts.main(argv)

        self.assertEqual(second_code, 1)
        self.assertIn("already exists", stderr.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
