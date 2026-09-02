#!/usr/bin/env python3
"""Build the MLB V8 March-August replay manifest without fabricating PIT evidence.

Provider folders determine only a source capability tier. A file from a Tier A source
is NOT automatically a decision snapshot. Exact raw bytes, matching sidecar metadata,
provider snapshot timestamp, request timestamp, and event commence time must prove a
canonical PIT target before Truth Gate decision-snapshot eligibility is recorded.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

POLICY = Path("config/mlb_v8_evidence_policy.json")
DEFAULT_INPUT = Path("artifacts/mlb_v8_replay_sources")
DEFAULT_OUTPUT = Path("artifacts/mlb_v8_replay_archive")
PIT_TARGET_TOLERANCE_MINUTES = 6.0


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_policy(path: Path = POLICY) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if value.get("policy_id") != "MLB_V8_EVIDENCE_V1" or not value.get("fail_closed"):
        raise RuntimeError("unexpected or non-fail-closed V8 evidence policy")
    return value


def parse_ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def dates_between(start: str, end: str):
    current = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while current <= stop:
        yield current.isoformat()
        current += timedelta(days=1)


def classify_source(name: str, registry: list[dict[str, Any]]) -> str:
    upper = name.upper()
    for row in registry:
        if str(row["source"]).upper() in upper:
            return str(row["tier"])
    return "UNREGISTERED"


def _sidecar(path: Path) -> Path:
    return path.with_name(path.stem + ".meta.json")


def _events(payload: Any) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return [dict(x) for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [dict(data)]
    return []


def verify_pit_snapshot(
    *, path: Path, raw: bytes, tier: str, policy: dict[str, Any]
) -> tuple[bool, str, list[dict[str, Any]], dict[str, Any] | None]:
    """Prove a raw provider file is a canonical PIT snapshot for one or more games."""
    if tier != "A_PIT_SNAPSHOT":
        return False, "SOURCE_TIER_NOT_A", [], None
    if path.name.endswith(".meta.json"):
        return False, "METADATA_FILE_NOT_RAW_SNAPSHOT", [], None
    sidecar = _sidecar(path)
    if not sidecar.is_file():
        return False, "PIT_SIDECAR_MISSING", [], None
    try:
        meta = json.loads(sidecar.read_text())
    except Exception:
        return False, "PIT_SIDECAR_INVALID_JSON", [], None
    if str(meta.get("payload_sha256") or "") != sha256_bytes(raw):
        return False, "PIT_RAW_SHA_MISMATCH", [], meta
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return False, "PIT_RAW_INVALID_JSON", [], meta
    requested_raw = ((meta.get("request_params_secret_free") or {}).get("date"))
    returned_raw = payload.get("timestamp") if isinstance(payload, dict) else None
    if not requested_raw or not returned_raw:
        return False, "PIT_REQUEST_OR_PROVIDER_TIMESTAMP_MISSING", [], meta
    try:
        requested = parse_ts(requested_raw)
        returned = parse_ts(returned_raw)
    except Exception:
        return False, "PIT_REQUEST_OR_PROVIDER_TIMESTAMP_INVALID", [], meta
    if returned > requested:
        return False, "PIT_PROVIDER_TIMESTAMP_AFTER_REQUEST", [], meta
    snapshot_lag_seconds = (requested - returned).total_seconds()
    # The Odds API historical interval is five minutes in the V8 replay era. Six
    # minutes allows timestamp-boundary jitter without accepting a stale snapshot.
    if snapshot_lag_seconds > PIT_TARGET_TOLERANCE_MINUTES * 60:
        return False, "PIT_PROVIDER_SNAPSHOT_TOO_OLD", [], meta

    targets = [float(x) for x in policy["canonical_capture_targets_minutes_before_first_pitch"]]
    matches: list[dict[str, Any]] = []
    for event in _events(payload):
        commence_raw = event.get("commence_time")
        event_id = str(event.get("id") or "").strip()
        if not commence_raw or not event_id:
            continue
        try:
            commence = parse_ts(commence_raw)
        except Exception:
            continue
        if returned >= commence:
            continue
        minutes_before = (commence - returned).total_seconds() / 60.0
        target = min(targets, key=lambda x: abs(minutes_before - x))
        delta = abs(minutes_before - target)
        if delta > PIT_TARGET_TOLERANCE_MINUTES:
            continue
        matches.append({
            "provider_event_id": event_id,
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "commence_time": commence.isoformat(),
            "provider_snapshot_at": returned.isoformat(),
            "requested_snapshot_at": requested.isoformat(),
            "snapshot_lag_seconds": round(snapshot_lag_seconds, 3),
            "minutes_before_first_pitch": round(minutes_before, 3),
            "canonical_target_minutes": int(target),
            "target_delta_minutes": round(delta, 3),
            "decision_target": int(target) == 30,
        })
    if not matches:
        return False, "PIT_NO_CANONICAL_GAME_TARGET_MATCH", [], meta
    decision = any(bool(x["decision_target"]) for x in matches)
    return decision, "PIT_DECISION_TARGET_VERIFIED" if decision else "PIT_CANONICAL_NONDECISION_TARGET_ONLY", matches, meta


def build(input_root: Path, output_root: Path) -> dict[str, Any]:
    policy = load_policy()
    window = policy["replay_window"]
    registry = policy["source_registry"]
    files: list[dict[str, Any]] = []
    coverage: dict[str, set[str]] = {}
    verified_pit_days: set[str] = set()

    if input_root.exists():
        for path in sorted(p for p in input_root.rglob("*") if p.is_file()):
            raw = path.read_bytes()
            rel = path.relative_to(input_root).as_posix()
            source_name = rel.split("/", 1)[0]
            tier = classify_source(source_name, registry)
            day = next((part for part in path.parts if len(part) == 10 and part[4:5] == "-" and part[7:8] == "-"), None)
            is_meta = path.name.endswith(".meta.json")
            eligible, pit_reason, pit_matches, _ = verify_pit_snapshot(
                path=path, raw=raw, tier=tier, policy=policy
            )
            files.append({
                "path": rel,
                "source": source_name,
                "record_role": "metadata" if is_meta else "raw_source",
                "evidence_tier": tier,
                "observed_date": day,
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "truth_gate_eligible_as_decision_snapshot": eligible,
                "pit_verification_reason": pit_reason,
                "pit_target_matches": pit_matches,
            })
            if day:
                coverage.setdefault(day, set()).add(tier)
                if eligible:
                    verified_pit_days.add(day)

    gaps = []
    for day in dates_between(window["start_date"], window["end_date"]):
        tiers = sorted(coverage.get(day, set()))
        tier_a_present = "A_PIT_SNAPSHOT" in tiers
        verified = day in verified_pit_days
        if verified:
            status = "PIT_DECISION_SNAPSHOT_VERIFIED"
        elif tier_a_present:
            status = "PIT_SOURCE_PRESENT_BUT_DECISION_SNAPSHOT_UNVERIFIED"
        else:
            status = "PIT_SOURCE_MISSING"
        gaps.append({
            "date": day,
            "tiers_present": tiers,
            "has_tier_a_source": tier_a_present,
            "has_verified_decision_snapshot": verified,
            "status": status,
        })

    manifest = {
        "schema": "MLB_V8_REPLAY_MANIFEST_V2",
        "policy_sha256": sha256_bytes(POLICY.read_bytes()),
        "window": window,
        "pit_target_tolerance_minutes": PIT_TARGET_TOLERANCE_MINUTES,
        "files": files,
        "file_count": len(files),
        "verified_pit_decision_days": len(verified_pit_days),
        "total_days": len(gaps),
        "promotion_eligible": False,
        "promotion_reason": "REPLAY_ARCHIVE_CANNOT_REPLACE_UNTOUCHED_V8_FORWARD_HOLDOUT",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output_root / "gap_report.json").write_text(json.dumps(gaps, indent=2, sort_keys=True) + "\n")
    return manifest


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        inp = root / "in"
        out = root / "out"
        a = inp / "THE_ODDS_API_HISTORICAL" / "2026-03-01" / "featured"
        a.mkdir(parents=True)
        raw_payload = {
            "timestamp": "2026-03-01T18:25:00Z",
            "previous_timestamp": "2026-03-01T18:20:00Z",
            "next_timestamp": "2026-03-01T18:30:00Z",
            "data": [{
                "id": "event-1",
                "commence_time": "2026-03-01T18:55:00Z",
                "home_team": "Home",
                "away_team": "Away",
                "bookmakers": [],
            }],
        }
        raw_path = a / "snapshot_20260301T183000Z.json"
        raw_bytes = (json.dumps(raw_payload, sort_keys=True) + "\n").encode()
        raw_path.write_bytes(raw_bytes)
        (a / "snapshot_20260301T183000Z.meta.json").write_text(json.dumps({
            "source": "THE_ODDS_API_HISTORICAL",
            "request_params_secret_free": {"date": "2026-03-01T18:30:00Z"},
            "payload_sha256": sha256_bytes(raw_bytes),
        }))

        unproved = inp / "THE_ODDS_API_HISTORICAL" / "2026-03-02" / "featured"
        unproved.mkdir(parents=True)
        (unproved / "snapshot_without_meta.json").write_text(json.dumps(raw_payload))

        c = inp / "SPORTSGAMEODDS_OPEN_CLOSE" / "2026-03-03"
        c.mkdir(parents=True)
        (c / "raw.json").write_text("{}\n")

        manifest = build(inp, out)
        rows = json.loads((out / "gap_report.json").read_text())
        raw_rows = [x for x in manifest["files"] if x["record_role"] == "raw_source"]
        proved = next(x for x in raw_rows if x["observed_date"] == "2026-03-01")
        missing_meta = next(x for x in raw_rows if x["observed_date"] == "2026-03-02")
        open_close = next(x for x in raw_rows if x["observed_date"] == "2026-03-03")
        assert manifest["promotion_eligible"] is False
        assert manifest["verified_pit_decision_days"] == 1
        assert rows[0]["status"] == "PIT_DECISION_SNAPSHOT_VERIFIED"
        assert rows[1]["status"] == "PIT_SOURCE_PRESENT_BUT_DECISION_SNAPSHOT_UNVERIFIED"
        assert rows[2]["status"] == "PIT_SOURCE_MISSING"
        assert proved["truth_gate_eligible_as_decision_snapshot"] is True
        assert proved["pit_target_matches"][0]["canonical_target_minutes"] == 30
        assert missing_meta["truth_gate_eligible_as_decision_snapshot"] is False
        assert missing_meta["pit_verification_reason"] == "PIT_SIDECAR_MISSING"
        assert open_close["truth_gate_eligible_as_decision_snapshot"] is False
    print(json.dumps({"status": "SELF_TEST_OK"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(args.input_root, args.output_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
