#!/usr/bin/env python3
"""Materialize NBA Results Pull rows only with preserved event/role evidence.

Research-only: successful JSON output is structurally joined, not
independently source-authenticated. No default/fabricated chronology.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from sportsedge.research.nba_early_season_evidence_join_v1 import join_nba_boxscore_evidence


def _hash_bytes(path):
    digest=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(path, key):
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or not isinstance(data.get(key),list):
        raise ValueError("NBA_EARLY_JOIN_MANIFEST_"+key.upper()+"_INVALID")
    if not all(isinstance(x,dict) for x in data[key]):
        raise ValueError("NBA_EARLY_JOIN_MANIFEST_ITEMS_INVALID")
    return data[key]


def build(*, box_csv: Path, event_manifest: Path, role_manifest: Path):
    with box_csv.open("r",encoding="utf-8-sig",newline="") as f:
        boxes=list(csv.DictReader(f))
    if not boxes:
        raise ValueError("NBA_EARLY_JOIN_BOXSCORE_ROWS_MISSING")
    events=_manifest(event_manifest,"events")
    roles=_manifest(role_manifest,"roles")
    outcome=join_nba_boxscore_evidence(boxes,events,roles)
    outcome["input_byte_sha256"]={
        "boxscore_csv":_hash_bytes(box_csv),
        "event_manifest":_hash_bytes(event_manifest),
        "role_manifest":_hash_bytes(role_manifest),
    }
    outcome["digest_semantics"]="RAW_FILE_BYTES_ONLY_NOT_PROVIDER_ATTESTATION"
    return outcome


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--box-csv",required=True,type=Path)
    ap.add_argument("--event-manifest",required=True,type=Path)
    ap.add_argument("--role-manifest",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args(argv)
    payload=build(box_csv=args.box_csv,
                  event_manifest=args.event_manifest,
                  role_manifest=args.role_manifest)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
