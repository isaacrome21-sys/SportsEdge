#!/usr/bin/env python3
"""Hash-verification re-pull for the CBR schedule-mirror successor manifest.

Successor to the College Basketball Reference leg recorded as
REFUSED_HTTP_403_NOT_PINNED by PR #2867: direct pulls from
sports-reference.com are refused under Sports Reference bot policy
(fail-closed; no circumvention), so the CBR season schedules are
pinned instead from the public GitHub mirror
mattwaite/mattwaite.github.io (sportsdatafiles/), whose own catalog
documents the files as the output of its CBB team game log scraper
over sports-reference.com/cbb.

The pin recorded in successor_manifest.json is commit-anchored:
repo + commit SHA + path + git blob SHA + size + SHA-256 of the
pulled bytes, plus the pull timestamp. This script re-downloads every
pinned file from its commit-addressed raw URL and compares size,
SHA-256 and the git blob SHA (SHA-1 over "blob <size>\\0" + bytes,
recomputable locally from the bytes alone). Any drift is reported as
SOURCE_CHANGED_AFTER_SNAPSHOT and the script exits nonzero — drift
is a refusal, never silent acceptance, and a drifted file may only
re-enter through a successor manifest with its own review.

No request is made to sports-reference.com by this script or anywhere
in this packet.

Stdlib only. Downloads go to memory; nothing is written into the
repository (this repo stores hashes and manifests, not data files).

Usage:  python3 pull_cbr_schedule_mirror.py
Exit codes: 0 all six pinned files match their pins, 2 at least one
refusal.
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


def git_blob_sha(raw):
    return hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()


def check(sample):
    url = sample["url"]
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        return {"file_name": sample["file_name"], "refusal": "ASSET_MISSING",
                "http_status": exc.code, "url": url}
    except urllib.error.URLError as exc:
        return {"file_name": sample["file_name"], "refusal": "SOURCE_UNAVAILABLE",
                "error": str(exc.reason), "url": url}
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != sample["bytes"]:
        return {"file_name": sample["file_name"], "refusal": "SIZE_MISMATCH",
                "expected_bytes": sample["bytes"], "got_bytes": len(raw), "url": url}
    if digest != sample["sha256"] or git_blob_sha(raw) != sample["git_blob_sha"]:
        return {"file_name": sample["file_name"],
                "refusal": "SOURCE_CHANGED_AFTER_SNAPSHOT",
                "expected_sha256": sample["sha256"], "got_sha256": digest,
                "expected_git_blob_sha": sample["git_blob_sha"],
                "got_git_blob_sha": git_blob_sha(raw), "url": url}
    return {"file_name": sample["file_name"], "status": "PIN_MATCH",
            "bytes": len(raw), "sha256": digest,
            "git_blob_sha": git_blob_sha(raw)}


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    results = [check(sample) for sample in manifest["samples"]]
    for result in results:
        print(json.dumps(result))
    print(json.dumps({"satisfies_precondition_c": manifest["satisfies"][
        "pr_2866_precondition_c_cbr_leg"][:3]}))
    return 0 if all(r.get("status") == "PIN_MATCH" for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
