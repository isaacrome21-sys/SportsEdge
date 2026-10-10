#!/usr/bin/env python3
"""Capture public 2025/2026 SportsDataverse CSV assets for prospective CFB scoring.

Writes a complete, SHA-pinned all-or-nothing bundle and capture timestamp.
This may be used only for future kicks as of capture. Never backfill predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from sportsedge.sports.cfb.sdv_live_scoring_source import DATASETS, FILES, LIVE_CONTRACT

TAGS = {
    "adv_team": "espn_cfb_adv_team",
    "adv_situational": "espn_cfb_adv_situational",
    "adv_drives": "espn_cfb_adv_drives",
    "cfb_schedules": "cfb_schedules",
}
BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"


def capture(directory: Path, *, opener=urlopen):
    directory = Path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".cfb-sdv-acq-", dir=directory.parent))
    complete = False
    try:
        items = {}
        for (year, dataset), filename in sorted(FILES.items()):
            url = f"{BASE}/{TAGS[dataset]}/{filename}"
            request = Request(url, headers={"User-Agent": "SportsEdge-CFB-Prospective/1"})
            with opener(request, timeout=45) as response:
                blob = response.read()
            if len(blob) < 100:
                raise ValueError("CFB_SDV_LIVE_DOWNLOAD_EMPTY:" + filename)
            (temp / filename).write_bytes(blob)
            items[filename] = {"sha256": hashlib.sha256(blob).hexdigest(),
                               "size": len(blob), "url": url}
        receipt = {"schema": LIVE_CONTRACT, "captured_at": datetime.now(timezone.utc).isoformat(),
                   "files": items}
        (temp / "receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if directory.exists():
            shutil.rmtree(directory)
        temp.rename(directory)
        complete = True
        print(f"CFB_SDV_PUBLIC_CAPTURE_OK files={len(items)} captured_at={receipt['captured_at']}")
    finally:
        if not complete:
            shutil.rmtree(temp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    capture(args.output_dir)


if __name__ == "__main__":
    main()
