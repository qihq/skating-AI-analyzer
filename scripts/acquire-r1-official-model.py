"""Acquire a pinned Ultralytics release via verified HTTPS; never deserialize weights.
Run fetch on this host or another trusted connected computer. Keep the entire output
bundle, including receipts. Stage validates bundle consistency, not its authenticity:
transport/receipt authenticity must come from the trusted acquisition computer.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

RELEASE = "v8.3.0"
SOURCE = f"https://github.com/ultralytics/assets/releases/download/{RELEASE}/yolov8n.pt"
METADATA = f"https://api.github.com/repos/ultralytics/assets/releases/tags/{RELEASE}"
HOSTS = {"github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
MAX_BYTES = 32 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Refusing non-official/non-HTTPS model URL")


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        self.chain.append({"from": req.full_url, "to": newurl, "status": code})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(output, timeout=20):
    output.mkdir(parents=True, exist_ok=False)
    redirect = OfficialRedirect()
    opener = urllib.request.build_opener(redirect)
    receipt = {"started_at": now(), "release": RELEASE, "source": SOURCE,
               "tls_validation": "Python default certificate and hostname verification",
               "status": "incomplete", "metadata_url": METADATA}
    metadata = None
    try:
        try:
            with opener.open(urllib.request.Request(METADATA, headers={"User-Agent": "skating-r1-model-acquisition"}), timeout=timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError("Metadata exceeds limit")
                (output / "github-release.json").write_bytes(raw)
                metadata = json.loads(raw)
                receipt["metadata_sha256"] = hashlib.sha256(raw).hexdigest()
        except Exception as exc:
            receipt["metadata_error"] = repr(exc)
        check_url(SOURCE)
        partial = output / "yolov8n.pt.part"
        digest = hashlib.sha256()
        count = 0
        with opener.open(urllib.request.Request(SOURCE, headers={"User-Agent": "skating-r1-model-acquisition"}), timeout=timeout) as response:
            check_url(response.url)
            if response.status != 200:
                raise ValueError(f"Unexpected HTTP status {response.status}")
            receipt["final_url"] = response.url
            receipt["http_status"] = response.status
            receipt["response_headers"] = dict(response.headers.items())
            with partial.open("xb") as stream:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > MAX_BYTES:
                        raise ValueError("Model exceeds bounded download size")
                    stream.write(block)
                    digest.update(block)
        if count < 1024 * 1024:
            raise ValueError("Response too small for selected YOLO model")
        with partial.open("rb") as stream:
            if stream.read(4) != b"PK\x03\x04":
                raise ValueError("Unexpected model container format; not deserialized")
        content_length = receipt["response_headers"].get("Content-Length")
        if content_length is not None and int(content_length) != count:
            raise ValueError("Incomplete Content-Length")
        sha = digest.hexdigest()
        official_digest = None
        asset_info = None
        if metadata is not None:
            if metadata.get("tag_name") != RELEASE:
                raise ValueError("Official metadata release mismatch")
            asset = next(x for x in metadata["assets"] if x["name"] == "yolov8n.pt")
            if asset["browser_download_url"] != SOURCE or asset["size"] != count:
                raise ValueError("Official asset URL/size mismatch")
            declared = asset.get("digest")
            if declared:
                if declared != "sha256:" + sha:
                    raise ValueError("Official asset digest mismatch")
                official_digest = declared
            asset_info = {k: asset.get(k) for k in ("id", "name", "size", "created_at", "updated_at", "browser_download_url", "digest")}
        partial.rename(output / "yolov8n.pt")
        receipt.update(status="downloaded", bytes=count, sha256=sha, official_digest=official_digest,
                       asset=asset_info, redirect_chain=redirect.chain, completed_at=now())
        write_json(output / "acquisition-receipt.json", receipt)
        receipt_sha = hashlib.sha256((output / "acquisition-receipt.json").read_bytes()).hexdigest()
        write_json(output / "model-source.json", {
            "source": SOURCE, "version": RELEASE, "final_url": receipt["final_url"],
            "bytes": count, "sha256": sha, "official_digest": official_digest,
            "hash_basis": "official digest matched" if official_digest else "local SHA256 of verified official TLS download; no independently published hash obtained",
            "acquired_at": receipt["completed_at"], "verification": "official TLS acquisition, no deserialization",
            "receipt_sha256": receipt_sha, "asset": asset_info,
        })
        return receipt
    except Exception as exc:
        receipt.update(status="failed", error=repr(exc), redirect_chain=redirect.chain, completed_at=now())
        write_json(output / "acquisition-receipt.json", receipt)
        raise


def stage(bundle, release):
    if not release.is_dir():
        raise ValueError("Release work directory must already exist")
    if (release / "manifest.json").exists() or list(release.glob("*.tar")):
        raise ValueError("Published release is immutable")
    destination = release / "models" / "yolov8n.pt"
    if destination.exists() or (release / "model-source.json").exists():
        raise ValueError("Refusing to overwrite staged model/source")
    source = json.loads((bundle / "model-source.json").read_text(encoding="utf-8"))
    receipt_raw = (bundle / "acquisition-receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    if source["source"] != SOURCE or source["version"] != RELEASE or receipt["source"] != SOURCE:
        raise ValueError("Unexpected official source/release")
    check_url(source["final_url"])
    if source["receipt_sha256"] != hashlib.sha256(receipt_raw).hexdigest() or receipt["status"] != "downloaded":
        raise ValueError("Invalid acquisition receipt")
    model = bundle / "yolov8n.pt"
    actual = hashlib.sha256(model.read_bytes()).hexdigest()
    if actual != source["sha256"] or actual != receipt["sha256"] or model.stat().st_size != source["bytes"] or source["bytes"] != receipt["bytes"]:
        raise ValueError("Bundle model hash/size mismatch")
    if receipt.get("official_digest") and receipt["official_digest"] != "sha256:" + actual:
        raise ValueError("Official digest mismatch")
    if receipt.get("metadata_sha256"):
        if hashlib.sha256((bundle / "github-release.json").read_bytes()).hexdigest() != receipt["metadata_sha256"]:
            raise ValueError("Raw metadata hash mismatch")
    destination.parent.mkdir(exist_ok=True)
    shutil.copy2(model, destination)
    source.update(staged_at=now(), acquisition_bundle=str(bundle.resolve()),
                  receipt_trust="Acquisition bundle supplied by trusted operator/computer; receipt is not a digital signature")
    write_json(release / "model-source.json", source)
    return source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_subparsers(dest="mode", required=True)
    f = modes.add_parser("fetch"); f.add_argument("--output", type=Path, required=True); f.add_argument("--timeout", type=int, default=20)
    s = modes.add_parser("stage"); s.add_argument("--bundle", type=Path, required=True); s.add_argument("--release", type=Path, required=True)
    args = p.parse_args()
    try:
        result = fetch(args.output, args.timeout) if args.mode == "fetch" else stage(args.bundle, args.release)
    except Exception as exc:
        print(f"FAILED: {exc!r}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
