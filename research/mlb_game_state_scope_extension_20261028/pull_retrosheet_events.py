#!/usr/bin/env python3
"""Pull the Retrosheet annual event zips and verify them against the pins
in extension_manifest.json (the PR #2856 pattern, extended to 2025 by the
MLB_GAME_STATE_V1 scope-extension packet).

Usage:
    python3 pull_retrosheet_events.py --out-dir /path/to/store

Downloads each zip from retrosheet.org (free public files; no account, no
payment), refuses any byte whose size or sha256 differs from the manifest
pin, and unzips into <out-dir>/events/<season>/. Data bytes live outside
the repo; only hashes are committed.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

MANIFEST = Path(__file__).with_name("extension_manifest.json")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    (out / "zips").mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest["zips"]:
        dest = out / "zips" / entry["file"]
        if not dest.exists():
            req = urllib.request.Request(
                entry["url"], headers={"User-Agent": "sportsedge-research/1.0"}
            )
            with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as fh:
                fh.write(resp.read())
        size = dest.stat().st_size
        digest = sha256_of(dest)
        ok = size == entry["bytes"] and digest == entry["sha256"]
        print(f"{entry['file']}: bytes={size} sha256={digest} "
              f"pin={'MATCH' if ok else 'MISMATCH'}")
        if not ok:
            print(f"REFUSED: {entry['file']} does not match its manifest pin")
            return 1
        season_dir = out / "events" / str(entry["season"])
        season_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest) as zf:
            zf.extractall(season_dir)
    print("all pins verified; events unzipped under", out / "events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
