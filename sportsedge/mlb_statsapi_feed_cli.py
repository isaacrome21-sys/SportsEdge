"""Build historical inning evidence from local MLB final-game feed JSON files.

Manifest schema:
{"schema":"MLB_FINAL_FEED_MANIFEST_V1","source_url":"https://...",
 "observed_at":"2026-10-01T00:00:00Z",
 "feed_paths":["game1.json","game2.json"]}

Feed paths are resolved relative to the manifest's parent directory.
No network access; no inferred timestamps; no overwrites.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sportsedge.mlb_statsapi_inning_converter import make_historical_export


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()
    if output_path.exists():
        raise FileExistsError("OUTPUT_ALREADY_EXISTS")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != "MLB_FINAL_FEED_MANIFEST_V1":
        raise ValueError("INVALID_FEED_MANIFEST")
    paths = manifest.get("feed_paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or not p for p in paths):
        raise ValueError("INVALID_FEED_PATHS")
    feeds = []
    hashes = []
    seen_paths = set()
    for relative in paths:
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("UNSAFE_FEED_PATH")
        path = (manifest_path.parent / rel).resolve()
        if not path.is_relative_to(manifest_path.parent) or path == manifest_path or path == output_path:
            raise ValueError("UNSAFE_FEED_PATH")
        if path in seen_paths:
            raise ValueError("DUPLICATE_FEED_PATH")
        seen_paths.add(path)
        data = path.read_bytes()
        hashes.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest()})
        feeds.append(json.loads(data))
    result = make_historical_export(
        feeds, source_url=manifest["source_url"], observed_at=manifest["observed_at"])
    result["source_files"] = hashes
    result["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with output_path.open("x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True, indent=2)
        out.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
