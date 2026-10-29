#!/usr/bin/env python3
"""Verify the G-PGA-2 content pins and the extractor's determinism.

Full mode (default): given the pull store and an extracted-content dir,
  (a) re-verify every raw page pin against the #2886 manifest;
  (b) re-run the extraction of record into a scratch dir and require
      every extracted event file AND the regenerated content manifest
      to be byte-identical to the kept copies (the determinism proof);
  (c) require the kept manifest's per-event hashes and corpus hash to
      match the kept extracted files.

Manifest-only mode (--manifest-only): validate the committed
content_manifest.json's internal consistency (counts, hash formats,
corpus hash recomputed from the per-event pins) without the store —
the mode the family tests exercise in CI.

Stdlib only. Exit 0 = all checks pass; 1 = any failure.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract_dg_content as ext  # noqa: E402


def check_manifest_consistency(manifest: dict) -> list:
    problems = []
    events = manifest["events"]
    if manifest["event_count"] != len(events):
        problems.append("event_count does not match events list")
    rows = sum(e["rows"] for e in events)
    if manifest["row_count"] != rows:
        problems.append("row_count does not match per-event rows")
    for e in events:
        for field in ("content_sha256", "source_page_sha256"):
            v = e[field]
            if len(v) != 64:
                problems.append(f"{e['event_id']}/{e['date']}: {field} malformed")
                continue
            try:
                int(v, 16)
            except ValueError:
                problems.append(f"{e['event_id']}/{e['date']}: {field} not hex")
    if ext.corpus_hash(events) != manifest["corpus_sha256"]:
        problems.append("corpus_sha256 does not recompute from per-event pins")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.expanduser("~/workspace/pga_screen_20261028/pulls"))
    ap.add_argument("--extracted", default=os.path.expanduser("~/workspace/pga_screen_20261028/extracted_content"))
    ap.add_argument("--manifest", default=os.path.join(HERE, "content_manifest.json"))
    ap.add_argument("--manifest-only", action="store_true")
    args = ap.parse_args()

    with open(args.manifest) as f:
        manifest = json.load(f)

    problems = check_manifest_consistency(manifest)
    if problems:
        for p in problems:
            print(f"MANIFEST INCONSISTENT: {p}")
        return 1
    print(
        f"manifest internally consistent: {manifest['event_count']} events, "
        f"{manifest['row_count']} rows, corpus {manifest['corpus_sha256'][:12]}…"
    )
    if args.manifest_only:
        print("manifest-only mode: store checks skipped")
        return 0

    # (c) kept extracted files match the kept manifest's pins.
    for e in manifest["events"]:
        path = os.path.join(args.extracted, e["content_file"])
        if not os.path.exists(path):
            print(f"MISSING extracted file: {e['content_file']}")
            return 1
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest != e["content_sha256"]:
            print(f"CONTENT PIN MISMATCH: {e['content_file']}")
            return 1
    print(f"kept extracted files match all {len(manifest['events'])} content pins")

    # (a)+(b) full re-extraction into a scratch dir; byte-compare.
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    raw_manifest_path = os.path.join(
        repo, "research", "pga_h2h_screen_20261028", "dg_pages_manifest.json"
    )
    with open(raw_manifest_path) as f:
        raw_manifest = json.load(f)
    try:
        events, stats = ext.extract_corpus(args.store, raw_manifest)
    except ValueError as e:
        print(f"RE-EXTRACTION ABORTED: {e}")
        return 1
    print(
        f"raw pins reverified during re-extraction: "
        f"{stats['raw_pages_reverified']}/{stats['raw_pages']}"
    )
    regen = ext.build_manifest(events, stats)
    if regen != manifest:
        print("DETERMINISM FAILURE: regenerated manifest differs from kept manifest")
        return 1
    with tempfile.TemporaryDirectory() as td:
        for (event_id, date), content in events.items():
            fname = f"{event_id}_{date}.json"
            kept = os.path.join(args.extracted, fname)
            with open(kept, "rb") as f:
                kept_bytes = f.read()
            if kept_bytes != ext.canonical_bytes(content):
                print(f"DETERMINISM FAILURE: {fname} differs on re-extraction")
                return 1
    print("determinism proof: re-extraction is byte-identical (all events + manifest)")
    print("CONTENT PINS VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
