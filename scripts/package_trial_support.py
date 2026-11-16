#!/usr/bin/env python3
"""Build the R1.2-P1 NAS trial-support package (Python standard library only).

Background
----------
The delivered R1.2 installation material shipped checksum sidecars written with
``Path.write_text(..., encoding="utf-8")`` on Windows, which produced CRLF line
endings.  The target NAS ``sha256sum -c`` then refused those files.  This tool rebuilds the
*installation support* material with LF-only, BOM-free checksum files and a new
install guide.  It never touches the application image, the ~900 MB tar or the
original release directory.

Contract
--------
* ``--release-dir``   original R1.2 release directory (read-only).
* ``--output-dir``    brand-new directory; it must not exist.
* ``--install-guide`` path to the new ``NAS-TRIAL-INSTALL.md`` guide.

The tar is verified against ``manifest.json`` (size + SHA-256) but is not copied
and is not put into the ZIP; the operator takes it from the original package.
The package revision is ``R1.2-P1`` and is deliberately different from the
application release/tag, which stays exactly as delivered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

PACKAGE_REVISION = "R1.2-P1"

ORIGINAL_MANIFEST_NAME = "manifest.json"
RENAMED_ORIGINAL_MANIFEST = "image-manifest.original.json"
INSTALL_GUIDE_NAME = "NAS-TRIAL-INSTALL.md"
PACKAGING_MANIFEST_NAME = "packaging-manifest.json"
ZIP_NAME = "trial-support.zip"
ZIP_SIDECAR_NAME = "trial-support.zip.sha256"

# Written before any payload and removed only after the finished package has
# been re-read and verified. A failed build keeps this marker so the directory
# can never be mistaken for a successful package.
INCOMPLETE_MARKER = "INCOMPLETE"
INCOMPLETE_TEXT = (
    b"INCOMPLETE: failed R1.2-P1 package build; do not publish, verify or reuse this directory.\n"
)

# Files copied byte-for-byte from the original release directory.
COPY_FILES = (
    "compose.r1-2.yml",
    "r1-2.env.example",
    "synthetic-no-person.mp4",
    "invalid-upload-fixture.mp4",
    "nas-feedback-template.json",
    "nas-trial-checklist.md",
)

REQUIRED_MANIFEST_FIELDS = (
    "tar",
    "tar_bytes",
    "tar_sha256",
    "tag",
    "image_id",
    "config_digest",
    "platform",
)

# Never listed in payload_files (self-reference / derived artifacts).
EXCLUDED_FROM_PAYLOAD = (
    PACKAGING_MANIFEST_NAME,
    ZIP_NAME,
    ZIP_SIDECAR_NAME,
)

READ_CHUNK = 1024 * 1024


class PackageError(Exception):
    """Raised when the support package cannot be built safely."""


# --------------------------------------------------------------------------
# small helpers (public on purpose: they are the testable building blocks)
# --------------------------------------------------------------------------

def sha256_file(path):
    """Stream a file and return its lowercase hex SHA-256."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(READ_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def checksum_line(digest, filename):
    """Return GNU sha256sum bytes: ``<hex><two spaces><basename><LF>``."""
    return "{0}  {1}\n".format(digest, filename).encode("ascii")


def write_checksum_sidecar(path, digest, filename):
    """Write a checksum sidecar as raw bytes (ASCII, LF, no BOM, no CR)."""
    Path(path).write_bytes(checksum_line(digest, filename))


def validate_tar_basename(name):
    """Accept only a plain, safe basename for the manifest ``tar`` value."""
    if not isinstance(name, str) or not name:
        raise PackageError("manifest field 'tar' must be a non-empty string")
    if name != name.strip():
        raise PackageError("manifest field 'tar' must not have leading/trailing whitespace")
    if name in (".", ".."):
        raise PackageError("manifest field 'tar' must be a file name, not '.' or '..'")
    for separator in ("/", "\\", "\x00"):
        if separator in name:
            raise PackageError(
                "manifest field 'tar' must be a safe basename without path separators: {0!r}".format(name)
            )
    if ":" in name:
        raise PackageError(
            "manifest field 'tar' must be a safe basename without drive/stream markers: {0!r}".format(name)
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise PackageError("manifest field 'tar' must not contain control characters")
    if name != Path(name).name:
        raise PackageError("manifest field 'tar' must be a safe basename: {0!r}".format(name))
    if not name.lower().endswith(".tar"):
        raise PackageError("manifest field 'tar' must end with '.tar': {0!r}".format(name))
    try:
        name.encode("ascii")
    except UnicodeEncodeError:
        raise PackageError(
            "manifest field 'tar' must be ASCII so the sha256sum sidecar stays ASCII: {0!r}".format(name)
        )
    return name


def resolve_tar_path(release_dir, tar_name):
    """Return the tar path inside ``release_dir`` after a basename safety check."""
    release_dir = Path(release_dir)
    name = validate_tar_basename(tar_name)
    candidate = release_dir / name
    if candidate.parent.resolve() != release_dir.resolve():
        raise PackageError("manifest tar must resolve directly inside the release directory")
    if candidate.is_symlink():
        raise PackageError("manifest tar must be a regular file, not a symlink: {0}".format(candidate))
    if not candidate.is_file():
        raise PackageError("manifest tar not found: {0}".format(candidate))
    return candidate


def verify_tar_identity(tar_path, expected_bytes, expected_sha256):
    """Verify actual tar size and SHA-256 against the manifest values."""
    tar_path = Path(tar_path)
    actual_bytes = tar_path.stat().st_size
    if actual_bytes != expected_bytes:
        raise PackageError(
            "tar size mismatch: manifest={0} actual={1} ({2})".format(expected_bytes, actual_bytes, tar_path)
        )
    actual_sha256 = sha256_file(tar_path)
    if actual_sha256 != expected_sha256:
        raise PackageError(
            "tar sha256 mismatch: manifest={0} actual={1} ({2})".format(
                expected_sha256, actual_sha256, tar_path
            )
        )
    return actual_sha256


def load_original_manifest(release_dir):
    """Read ``manifest.json`` and return ``(parsed, raw_bytes)``."""
    manifest_path = Path(release_dir) / ORIGINAL_MANIFEST_NAME
    if not manifest_path.is_file():
        raise PackageError("original manifest not found: {0}".format(manifest_path))
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackageError("original manifest is not valid UTF-8 JSON: {0}".format(manifest_path)) from exc
    if not isinstance(manifest, dict):
        raise PackageError("original manifest must be a JSON object: {0}".format(manifest_path))
    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            raise PackageError("original manifest is missing required field {0!r}".format(field))
    return manifest, raw


def _require_text(manifest, field):
    value = manifest.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PackageError("manifest field {0!r} must be a non-empty string".format(field))
    return value


def _require_int(manifest, field):
    value = manifest.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PackageError("manifest field {0!r} must be a non-negative integer".format(field))
    return value


def _require_sha256(manifest, field):
    value = manifest.get(field)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise PackageError("manifest field {0!r} must be a 64-character hex sha256".format(field))
    return value.lower()


def _record(path, name):
    return {"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _json_bytes(payload):
    """Serialise JSON as UTF-8 bytes with LF and no BOM (no text-mode translation)."""
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _packaging_manifest(manifest, manifest_raw, revision, payload_records, tar_name, tar_bytes, tar_sha256):
    tar_sidecar_name = tar_name + ".sha256"
    return {
        "schema_version": 1,
        "package_revision": revision,
        "package_kind": "R1.2 installation-material correction (checksum newline fix); application image unchanged",
        "application_release": manifest.get("release"),
        "application_date": manifest.get("date"),
        "note": (
            "Package revision {0} is a packaging revision only and is not an application image "
            "version. The image tag, tar bytes and tar sha256 are unchanged from the original R1.2 "
            "image manifest.".format(revision)
        ),
        "image_identity": {
            "tag": manifest.get("tag"),
            "image_id": manifest.get("image_id"),
            "image_id_kind": manifest.get("image_id_kind"),
            "config_digest": manifest.get("config_digest"),
            "platform": manifest.get("platform"),
            "registry_pushed": manifest.get("registry_pushed"),
            "registry_published_digest": manifest.get("registry_published_digest"),
            "tar": tar_name,
            "tar_bytes": tar_bytes,
            "tar_sha256": tar_sha256,
        },
        "original_manifest": {
            "source_name": ORIGINAL_MANIFEST_NAME,
            "renamed_copy": RENAMED_ORIGINAL_MANIFEST,
            "bytes_preserved": True,
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "target_nas_verified_in_original_manifest": manifest.get("target_nas_verified"),
            "note": (
                "The original manifest.json is copied byte-for-byte as "
                "image-manifest.original.json. target_nas_verified_in_original_manifest records "
                "the value that was in the original manifest at packaging time; it is historical "
                "packaging input and is not a statement about the current NAS state. No field is "
                "rewritten or updated by this packaging revision."
            ),
        },
        "tar_transport": {
            "included_in_zip": False,
            "must_be_taken_from_original_package": True,
            "expected_basename": tar_name,
            "expected_bytes": tar_bytes,
            "expected_sha256": tar_sha256,
            "sha256_sidecar": tar_sidecar_name,
            "sidecar_format": (
                "GNU sha256sum: <64 lowercase hex><two spaces><basename><LF>; ASCII, no BOM, no CR"
            ),
        },
        "checksum_files": {
            "tar_sidecar": tar_sidecar_name,
            "zip_sidecar": ZIP_SIDECAR_NAME,
            "newline": "LF only (0x0A); written as bytes, never through text-mode newline translation",
            "zip_sha256_location": (
                "trial-support.zip.sha256 (external sidecar; intentionally not recorded inside the zip)"
            ),
        },
        "payload_files": payload_records,
        "excluded_from_payload": list(EXCLUDED_FROM_PAYLOAD),
        "exclusion_reason": (
            "packaging-manifest.json cannot contain its own hash; trial-support.zip cannot contain "
            "itself; trial-support.zip.sha256 is derived from the zip. These three files are never "
            "listed in payload_files and the zip never contains itself or its sidecar."
        ),
    }


def write_zip(zip_path, output_dir, names):
    """Write the support ZIP with exactly the given entry basenames."""
    output_dir = Path(output_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(output_dir / name, arcname=name)


def verify_output(output_dir, payload_records, tar_name):
    """Re-read the finished package and fail if anything is inconsistent."""
    output_dir = Path(output_dir)
    declared = {}
    for record in payload_records:
        if record["path"] in declared:
            raise PackageError("duplicate payload path: {0}".format(record["path"]))
        declared[record["path"]] = record

    for name, record in declared.items():
        path = output_dir / name
        if not path.is_file():
            raise PackageError("payload file missing after build: {0}".format(name))
        actual = _record(path, name)
        if actual != record:
            raise PackageError("payload record mismatch after build: {0}".format(name))

    expected_names = set(declared) | {PACKAGING_MANIFEST_NAME}
    zip_path = output_dir / ZIP_NAME
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise PackageError("zip entry set does not match the payload list")
        if tar_name in names or any(name.endswith(".tar") for name in names):
            raise PackageError("the application tar must not be inside the support zip")
        for name, record in declared.items():
            data = archive.read(name)
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise PackageError("zip entry does not match payload record: {0}".format(name))
        if archive.read(PACKAGING_MANIFEST_NAME) != (output_dir / PACKAGING_MANIFEST_NAME).read_bytes():
            raise PackageError("packaging manifest inside the zip differs from the output copy")


def mark_incomplete(output_dir):
    """Make a failed build unmistakable; never swallow cleanup errors.

    The failed directory is kept as evidence (no recursive delete). The final
    ZIP checksum sidecar is removed so the remains cannot pass a
    ``sha256sum -c`` check. Returns a list of problems (empty when the marker
    is in place and the sidecar is gone); the caller must not ignore it.
    """
    output_dir = Path(output_dir)
    problems = []
    try:
        (output_dir / INCOMPLETE_MARKER).write_bytes(INCOMPLETE_TEXT)
    except OSError as exc:
        problems.append("could not write {0}: {1}".format(INCOMPLETE_MARKER, exc))
    sidecar = output_dir / ZIP_SIDECAR_NAME
    try:
        if sidecar.exists() or sidecar.is_symlink():
            sidecar.unlink()
    except OSError as exc:
        problems.append("could not remove {0}: {1}".format(ZIP_SIDECAR_NAME, exc))
    return problems


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------

def build_package(release_dir, output_dir, install_guide, revision=PACKAGE_REVISION):
    """Build the support package and return a JSON-serialisable summary.

    All read-only validation happens before the output directory is created.
    A write-time failure keeps the directory as evidence: it is marked
    INCOMPLETE, the final ZIP checksum sidecar is removed, and any later run
    refuses to reuse the directory, so a failed build can never be mistaken
    for a successful package.
    """
    release_dir = Path(release_dir)
    output_dir = Path(output_dir)
    install_guide = Path(install_guide)

    if output_dir.exists():
        if (output_dir / INCOMPLETE_MARKER).is_file():
            raise PackageError(
                "output directory is marked {0} by a previous failed build and must not be "
                "reused: {1}".format(INCOMPLETE_MARKER, output_dir)
            )
        raise PackageError("output directory already exists, refusing to overwrite: {0}".format(output_dir))
    if not release_dir.is_dir():
        raise PackageError("release directory not found: {0}".format(release_dir))
    if not install_guide.is_file():
        raise PackageError("install guide not found: {0}".format(install_guide))
    resolved_release = release_dir.resolve()
    resolved_output = output_dir.resolve()
    if resolved_release == resolved_output or resolved_release in resolved_output.parents:
        raise PackageError("output directory must live outside the source release directory")

    manifest, manifest_raw = load_original_manifest(release_dir)
    tar_name = validate_tar_basename(_require_text(manifest, "tar"))
    tar_bytes = _require_int(manifest, "tar_bytes")
    tar_sha256 = _require_sha256(manifest, "tar_sha256")
    for field in ("tag", "image_id", "config_digest", "platform"):
        _require_text(manifest, field)

    tar_path = resolve_tar_path(release_dir, tar_name)
    verify_tar_identity(tar_path, tar_bytes, tar_sha256)

    copied_sources = []
    for name in COPY_FILES:
        source = release_dir / name
        if not source.is_file():
            raise PackageError("required input missing or not a regular file: {0}".format(source))
        copied_sources.append((source, name))

    created = False
    try:
        output_dir.mkdir(parents=True)
        created = True
        (output_dir / INCOMPLETE_MARKER).write_bytes(INCOMPLETE_TEXT)

        payload_records = []
        for source, name in copied_sources:
            shutil.copyfile(source, output_dir / name)
            payload_records.append(_record(output_dir / name, name))

        renamed_manifest = output_dir / RENAMED_ORIGINAL_MANIFEST
        renamed_manifest.write_bytes(manifest_raw)
        payload_records.append(_record(renamed_manifest, RENAMED_ORIGINAL_MANIFEST))

        shutil.copyfile(install_guide, output_dir / INSTALL_GUIDE_NAME)
        payload_records.append(_record(output_dir / INSTALL_GUIDE_NAME, INSTALL_GUIDE_NAME))

        tar_sidecar_name = tar_name + ".sha256"
        write_checksum_sidecar(output_dir / tar_sidecar_name, tar_sha256, tar_name)
        payload_records.append(_record(output_dir / tar_sidecar_name, tar_sidecar_name))

        packaging = _packaging_manifest(
            manifest, manifest_raw, revision, payload_records, tar_name, tar_bytes, tar_sha256
        )
        (output_dir / PACKAGING_MANIFEST_NAME).write_bytes(_json_bytes(packaging))

        zip_path = output_dir / ZIP_NAME
        write_zip(
            zip_path,
            output_dir,
            [record["path"] for record in payload_records] + [PACKAGING_MANIFEST_NAME],
        )
        zip_sha256 = sha256_file(zip_path)
        write_checksum_sidecar(output_dir / ZIP_SIDECAR_NAME, zip_sha256, ZIP_NAME)

        verify_output(output_dir, payload_records, tar_name)
        (output_dir / INCOMPLETE_MARKER).unlink()
    except BaseException as exc:
        if created:
            problems = mark_incomplete(output_dir)
            if problems:
                raise PackageError(
                    "build failed and the {0} marker could not be finalised: {1}".format(
                        INCOMPLETE_MARKER, "; ".join(problems)
                    )
                ) from exc
        raise

    return {
        "package_revision": revision,
        "application_tag": manifest.get("tag"),
        "application_release": manifest.get("release"),
        "output_dir": str(output_dir),
        "zip": ZIP_NAME,
        "zip_bytes": (output_dir / ZIP_NAME).stat().st_size,
        "zip_sha256": zip_sha256,
        "tar": tar_name,
        "tar_bytes": tar_bytes,
        "tar_sha256": tar_sha256,
        "tar_included_in_zip": False,
        "payload_files": [record["path"] for record in payload_records],
        "packaging_manifest": PACKAGING_MANIFEST_NAME,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="package_trial_support.py",
        description=(
            "Build the R1.2-P1 NAS trial-support package (LF checksum fix; "
            "application image and tar unchanged)."
        ),
    )
    parser.add_argument("--release-dir", required=True, help="original R1.2 release directory (read-only)")
    parser.add_argument("--output-dir", required=True, help="new output directory; must not exist")
    parser.add_argument("--install-guide", required=True, help="path to the new NAS-TRIAL-INSTALL.md guide")
    args = parser.parse_args(argv)

    try:
        summary = build_package(args.release_dir, args.output_dir, args.install_guide)
    except PackageError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
