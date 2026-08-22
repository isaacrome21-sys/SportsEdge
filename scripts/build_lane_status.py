#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LANES = ("archive_latest.json", "nrfi_latest.json")
STALE_AFTER_SECONDS = {
    "archive": 3 * 60 * 60,
    "nrfi": 36 * 60 * 60,
}
CT = ZoneInfo("America/Chicago")
# Archive captures can legitimately be idle overnight. T-180 capture opportunities
# can begin in the morning and late West Coast games can keep the lane active past
# midnight CT, so only suppress ordinary age-based staleness from 02:00-08:00 CT.
ARCHIVE_QUIET_START_HOUR_CT = 2
ARCHIVE_QUIET_END_HOUR_CT = 8


def _parse_utc(value: str | None):
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _archive_quiet_window(now: datetime) -> bool:
    hour = now.astimezone(CT).hour
    return ARCHIVE_QUIET_START_HOUR_CT <= hour < ARCHIVE_QUIET_END_HOUR_CT


def load_json_state(path: Path):
    if not path.exists():
        return "MISSING", None, None
    try:
        return "OK", json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return "UNREADABLE", None, f"{type(exc).__name__}:{exc}"


def build(root: Path, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    hb = root / "runtime/heartbeat"
    lanes = {}
    for name in LANES:
        p = hb / name
        pointer_state, d, pointer_error = load_json_state(p)
        lane = name.removesuffix("_latest.json")
        pointer_rel = str(p.relative_to(root))

        if pointer_state == "MISSING":
            lanes[lane] = {
                "state": "POINTER_MISSING",
                "pointer_state": "MISSING",
                "pointer": pointer_rel,
            }
            continue

        if pointer_state == "UNREADABLE" or not isinstance(d, dict):
            lanes[lane] = {
                "state": "POINTER_UNREADABLE",
                "pointer_state": "UNREADABLE",
                "pointer": pointer_rel,
                "pointer_error": pointer_error or "pointer JSON is not an object",
            }
            continue

        source_rel = d.get("source_artifact")
        source = root / source_rel if source_rel else None
        source_ok = bool(source_rel and source and source.is_file())
        durable_at = _parse_utc(d.get("last_durable_at_utc"))
        age_seconds = None
        if durable_at is not None:
            age_seconds = max(0, int((now - durable_at).total_seconds()))
        stale_after = STALE_AFTER_SECONDS[lane]
        quiet_window = lane == "archive" and _archive_quiet_window(now)

        if not source_ok:
            state = "POINTER_SOURCE_MISSING"
        elif durable_at is None:
            state = "POINTER_TIMESTAMP_UNREADABLE"
        elif lane == "archive" and quiet_window and age_seconds is not None and age_seconds > stale_after:
            state = "LANE_QUIET_WINDOW"
        elif age_seconds is not None and age_seconds > stale_after:
            state = "LANE_STALE"
        else:
            state = "LANE_FRESH"

        lanes[lane] = {
            "state": state,
            "pointer_state": "OK",
            "pointer": pointer_rel,
            "last_durable_at_utc": d.get("last_durable_at_utc"),
            "age_seconds": age_seconds,
            "stale_after_seconds": stale_after,
            "quiet_window_active": quiet_window,
            "quiet_window_ct": "02:00-08:00" if lane == "archive" else None,
            "pointer_updated_at_utc": d.get("pointer_updated_at_utc"),
            "durable_commit_sha": d.get("durable_commit_sha"),
            "source_artifact": source_rel,
            "source_artifact_sha256": d.get("source_artifact_sha256"),
            "source_exists": source_ok,
            "status": d.get("status"),
            "evidence_count": d.get("evidence_count"),
            "workflow_run_id": d.get("workflow_run_id"),
            "trigger": d.get("trigger"),
        }
    return {
        "generated_at_utc": now.isoformat(),
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
