#!/usr/bin/env python3
"""Hash-verification re-pull for the hoopR MBB play-by-play admission manifest.

The play-by-play assets live in the same ROLLING release family as the
schedules admitted by PR #2867: release
``espn_mens_college_basketball_pbp`` (release ID 97399228) of
``sportsdataverse/sportsdataverse-data``. Assets are replaced in place
under a stable tag, so the pin recorded in pbp_manifest.json is the full
tuple (tag + release ID + asset ID + size + updated_at + SHA-256) plus
the pull timestamp — it attests the bytes as pulled at
retrieved_at_utc, the strongest attestation this source supports. This
script re-downloads every pinned play-by-play CSV and compares size and
SHA-256 against the manifest. Any drift is reported as
SOURCE_CHANGED_AFTER_SNAPSHOT and the script exits nonzero — drift is a
refusal, never silent acceptance, and a drifted asset may only re-enter
through a successor manifest with its own review.

Adaptation vs pull_hoopr_mbb_schedules.py (PR #2867): the schedule
assets are ~4 MB and are fetched to memory; a play-by-play season CSV
is 549-843 MB, so this script streams to disk in chunks and hashes
incrementally. Downloads land in a scratch directory OUTSIDE the
repository (this repo stores hashes and manifests, not data files):
pass --out-dir or set SPORTSEDGE_PBP_PULL_DIR. With --verify-only the
script hashes files already present in the output directory instead of
downloading.

The .parquet and .rds twins of each season exist upstream and are
deliberately NOT pinned (see pbp_manifest.json, key
``unpinned_twin_formats``): the SportsEdge runtime has no parquet
reader, the .rds serialization is the R route and is not consumed here,
and formats are pinned independently — one format's pin never vouches
for another.

Stdlib only.

Usage:  python3 pull_hoopr_pbp.py --out-dir /path/to/scratch
        python3 pull_hoopr_pbp.py --out-dir /path/to/scratch --verify-only
Exit codes: 0 all pinned assets match their pins, 2 at least one refusal.
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent / "pbp_manifest.json"
CHUNK = 1 << 22


def hash_stream(chunks):
    digest = hashlib.sha256()
    total = 0
    for chunk in chunks:
        digest.update(chunk)
        total += len(chunk)
    return total, digest.hexdigest()


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "sportsedge-admission-probe"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as fh:
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            fh.write(chunk)
            digest.update(chunk)
            total += len(chunk)
    tmp.rename(dest)
    return total, digest.hexdigest()


def hash_file(path):
    with open(path, "rb") as fh:
        return hash_stream(iter(lambda: fh.read(CHUNK), b""))


def check(sample, out_dir, verify_only):
    url = sample["url"]
    dest = out_dir / sample["asset_name"]
    try:
        if verify_only:
            if not dest.exists():
                return {"asset_name": sample["asset_name"], "refusal": "ASSET_MISSING",
                        "detail": "not present in out-dir under --verify-only", "url": url}
            size, digest = hash_file(dest)
        else:
            size, digest = download(url, dest)
    except urllib.error.HTTPError as exc:
        return {"asset_name": sample["asset_name"], "refusal": "ASSET_MISSING",
                "http_status": exc.code, "url": url}
    except urllib.error.URLError as exc:
        return {"asset_name": sample["asset_name"], "refusal": "SOURCE_UNAVAILABLE",
                "error": str(exc.reason), "url": url}
    if size != sample["bytes"]:
        return {"asset_name": sample["asset_name"], "refusal": "SIZE_MISMATCH",
                "expected_bytes": sample["bytes"], "got_bytes": size, "url": url}
    if digest != sample["sha256"]:
        return {"asset_name": sample["asset_name"],
                "refusal": "SOURCE_CHANGED_AFTER_SNAPSHOT",
                "expected_sha256": sample["sha256"], "got_sha256": digest, "url": url}
    return {"asset_name": sample["asset_name"], "status": "PIN_MATCH",
            "bytes": size, "sha256": digest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=os.environ.get("SPORTSEDGE_PBP_PULL_DIR"),
                        help="scratch directory outside the repository for the CSV bytes")
    parser.add_argument("--verify-only", action="store_true",
                        help="hash files already in --out-dir instead of downloading")
    args = parser.parse_args(argv)
    if not args.out_dir:
        print(json.dumps({"refusal": "SOURCE_UNAVAILABLE",
                          "error": "--out-dir (or SPORTSEDGE_PBP_PULL_DIR) is required"}))
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    results = [check(sample, out_dir, args.verify_only) for sample in manifest["samples"]]
    for result in results:
        print(json.dumps(result))
    return 0 if all(r.get("status") == "PIN_MATCH" for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
