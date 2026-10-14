#!/usr/bin/env python3
"""Reassemble the published recount inputs from their base64 parts.

Reads PUBLISHED_INPUTS_MANIFEST.json (beside this script), verifies every
part file's SHA-256, decodes and concatenates the parts of each logical
file, verifies the reassembled file's SHA-256 and size against the
manifest, and writes it to the staging layout under --out:

    <out>/sources/schedules/cfb_schedule_<season>.csv.gz   (2013-2025)
    <out>/sources/cfb_line_odds.csv.gz
    <out>/sources/cfb_team_info_2024.parquet
    <out>/snapshots/{results,lines,directory}_snapshot.json
    <out>/snapshots/{SNAPSHOT_MANIFEST,DRY_RUN_MANIFEST}.json

Any hash or size mismatch aborts with a message naming the file (exit 2)
and no partial file is left in place. Standard library only.
"""

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True,
                    help="output directory for the reassembled input tree")
    ap.add_argument("--root", default=str(HERE),
                    help="package root holding sources/ and snapshots/ "
                         "part directories (default: this script's folder)")
    args = ap.parse_args()
    root = Path(args.root)
    out = Path(args.out)
    manifest = json.loads((HERE / "PUBLISHED_INPUTS_MANIFEST.json").read_text())

    failures = []
    written = 0
    for entry in manifest["files"]:
        subdir = entry["target"].split("/")[0]
        chunks = []
        for part in entry["parts"]:
            ppath = root / subdir / part["file"]
            if not ppath.is_file():
                failures.append(f"{ppath}: MISSING PART")
                continue
            pdata = ppath.read_bytes()
            if sha256(pdata) != part["sha256"] or len(pdata) != part["size_bytes"]:
                failures.append(f"{ppath}: part hash/size mismatch")
                continue
            chunks.append(base64.b64decode(pdata.strip(), validate=True))
        if failures:
            continue
        data = b"".join(chunks)
        if sha256(data) != entry["sha256"] or len(data) != entry["size_bytes"]:
            failures.append(
                f"{entry['target']}: reassembled sha256/size mismatch")
            continue
        dest = out / entry["target"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1
        print(f"OK {entry['target']}  {len(data)} B  sha256={entry['sha256']}")
    if failures:
        for f in failures:
            print(f"REASSEMBLY FAILED: {f}", file=sys.stderr)
        raise SystemExit(2)
    print(f"REASSEMBLED: {written} files into {out}")


if __name__ == "__main__":
    main()
