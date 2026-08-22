#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

LANES = ("archive_latest.json", "nrfi_latest.json")


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build(root: Path) -> dict:
    hb = root / "runtime/heartbeat"
    lanes = {}
    for name in LANES:
        p = hb / name
        d = load_json(p)
        lane = name.removesuffix("_latest.json")
        if not d:
            lanes[lane] = {"state": "NO_POINTER", "pointer": str(p.relative_to(root))}
            continue
        source = root / d.get("source_artifact", "")
        source_ok = source.is_file()
        lanes[lane] = {
            "state": "POINTER_SOURCE_OK" if source_ok else "POINTER_SOURCE_MISSING",
            "pointer": str(p.relative_to(root)),
            "last_durable_at_utc": d.get("last_durable_at_utc"),
            "durable_commit_sha": d.get("durable_commit_sha"),
            "source_artifact": d.get("source_artifact"),
            "source_exists": source_ok,
            "status": d.get("status"),
        }
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "role": "DERIVED_STATUS_VIEW_POINTERS_ARE_CACHE_CANONICAL_ARTIFACTS_WIN",
        "lanes": lanes,
        "model_eligibility_is_separate": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--output", default="runtime/heartbeat/STATUS.json")
    args = ap.parse_args()
    root = Path(args.data_root).resolve()
    out = root / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(root), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
