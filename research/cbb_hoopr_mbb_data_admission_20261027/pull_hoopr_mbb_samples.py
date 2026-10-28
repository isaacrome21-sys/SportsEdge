#!/usr/bin/env python3
"""Hash-verification re-pull for the hoopR MBB substrate admission.

Release tags in sportsdataverse/sportsdataverse-data are ROLLING: assets
are replaced in place under a stable tag. The pin is therefore the tuple
recorded in sample_manifest.json (tag + asset ID + size + updated_at +
SHA-256). This script re-downloads every pinned asset and compares size
and SHA-256 against the manifest. Any drift is reported as
SOURCE_CHANGED_AFTER_SNAPSHOT and the script exits nonzero — drift is a
refusal, never silent acceptance, and a drifted asset may only re-enter
through a successor manifest with its own review.

Stdlib only. Downloads go to memory / a temp dir; nothing is written into
the repository (this repo stores hashes and manifests, not data files).

Usage:  python3 pull_hoopr_mbb_samples.py
Exit codes: 0 all assets match their pins, 2 at least one refusal.
"""

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent / "sample_manifest.json"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sportsedge-admission-probe"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def check(sample):
    url = sample["url"]
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        return {"asset_name": sample["asset_name"], "refusal": "ASSET_MISSING",
                "http_status": exc.code, "url": url}
    except urllib.error.URLError as exc:
        return {"asset_name": sample["asset_name"], "refusal": "SOURCE_UNAVAILABLE",
                "error": str(exc.reason), "url": url}
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != sample["bytes"]:
        return {"asset_name": sample["asset_name"], "refusal": "SIZE_MISMATCH",
                "expected_bytes": sample["bytes"], "got_bytes": len(raw), "url": url}
    if digest != sample["sha256"]:
        return {"asset_name": sample["asset_name"],
                "refusal": "SOURCE_CHANGED_AFTER_SNAPSHOT",
                "expected_sha256": sample["sha256"], "got_sha256": digest, "url": url}
    return {"asset_name": sample["asset_name"], "status": "PIN_MATCH",
            "bytes": len(raw), "sha256": digest}


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    results = [check(sample) for sample in manifest["samples"]]
    for result in results:
        print(json.dumps(result))
    return 0 if all(r.get("status") == "PIN_MATCH" for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
