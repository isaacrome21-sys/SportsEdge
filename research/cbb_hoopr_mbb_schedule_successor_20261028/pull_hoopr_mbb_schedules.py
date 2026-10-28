#!/usr/bin/env python3
"""Hash-verification re-pull for the hoopR MBB schedule successor manifest.

Successor to pull_hoopr_mbb_samples.py (PR #2835). Release tags in
sportsdataverse/sportsdataverse-data are ROLLING: assets are replaced in
place under a stable tag, so the pin recorded in successor_manifest.json
is the full tuple (tag + release ID + asset ID + size + updated_at +
SHA-256) plus the pull timestamp — it attests the bytes as pulled at
retrieved_at_utc, the strongest attestation this source supports. This
script re-downloads every pinned schedule asset and compares size and
SHA-256 against the manifest. Any drift is reported as
SOURCE_CHANGED_AFTER_SNAPSHOT and the script exits nonzero — drift is a
refusal, never silent acceptance, and a drifted asset may only re-enter
through a successor manifest with its own review.

The College Basketball Reference leg is NOT re-pulled here: it was
refused upstream (HTTP 403) at admission time and is recorded in the
manifest as REFUSED_HTTP_403_NOT_PINNED; this script reports that status
verbatim. Sports Reference bot policy is fail-closed.

Stdlib only. Downloads go to memory; nothing is written into the
repository (this repo stores hashes and manifests, not data files).

Usage:  python3 pull_hoopr_mbb_schedules.py
Exit codes: 0 all pinned schedule assets match their pins, 2 at least
one refusal.
"""

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent / "successor_manifest.json"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sportsedge-admission-probe"})
    with urllib.request.urlopen(req, timeout=300) as resp:
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
    cbr = manifest["cbr_leg"]
    print(json.dumps({"cbr_leg_status": cbr["status"],
                      "attempted_at_utc": cbr["attempted_at_utc"]}))
    return 0 if all(r.get("status") == "PIN_MATCH" for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
