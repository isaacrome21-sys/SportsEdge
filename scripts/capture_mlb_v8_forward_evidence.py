#!/usr/bin/env python3
"""Persist immutable V8 decision/close evidence records.

The runner that produces a recommendation writes a JSON payload and calls this tool
with phase=decision before exposure. A pre-first-pitch close collector calls it with
phase=close. Records are content-addressed and append-only; conflicting rewrites fail.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path("artifacts/mlb_v8_forward")
POLICY = Path("config/mlb_v8_evidence_policy.json")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_ts(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def validate(payload: dict[str, Any], phase: str) -> None:
    required = ["game_id", "first_pitch_at", "captured_at", "quotes", "source_provenance"]
    if phase == "decision":
        required += ["run_id", "model_sha", "distribution_sha"]
    missing = [key for key in required if payload.get(key) in (None, "", [], {})]
    if missing:
        raise ValueError("missing required V8 evidence fields: " + ",".join(missing))
    first_pitch = parse_ts(str(payload["first_pitch_at"]))
    captured = parse_ts(str(payload["captured_at"]))
    if captured >= first_pitch:
        raise ValueError("V8 pregame evidence must be captured before first pitch")
    if not isinstance(payload["quotes"], list) or not payload["quotes"]:
        raise ValueError("quotes must be a non-empty list")
    for quote in payload["quotes"]:
        for key in ("book_key", "market", "price", "retrieved_at"):
            if quote.get(key) in (None, ""):
                raise ValueError(f"quote missing {key}")
        retrieved = parse_ts(str(quote["retrieved_at"]))
        if retrieved > captured:
            raise ValueError("quote retrieved_at cannot be after captured_at")


def persist(payload: dict[str, Any], phase: str, root: Path = ROOT) -> Path:
    validate(payload, phase)
    policy_raw = POLICY.read_bytes()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    record_sha = sha(canonical)
    day = parse_ts(str(payload["first_pitch_at"])).date().isoformat()
    game = str(payload["game_id"]).replace("/", "_")
    destination = root / day / game / phase / f"{record_sha}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema": "MLB_V8_FORWARD_EVIDENCE_V1",
        "phase": phase,
        "record_sha256": record_sha,
        "policy_sha256": sha(policy_raw),
        "payload": payload,
    }
    encoded = (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode()
    if destination.exists() and destination.read_bytes() != encoded:
        raise RuntimeError("immutable V8 evidence collision")
    destination.write_bytes(encoded)
    print(json.dumps({"status": "CAPTURED", "phase": phase, "path": str(destination), "sha256": record_sha}))
    return destination


def self_test() -> int:
    import tempfile
    base = {
        "game_id": "123",
        "first_pitch_at": "2026-09-03T23:05:00Z",
        "captured_at": "2026-09-03T22:00:00Z",
        "quotes": [{"book_key": "draftkings", "market": "h2h", "price": -120, "retrieved_at": "2026-09-03T21:59:50Z"}],
        "source_provenance": {"provider": "THE_ODDS_API", "raw_sha256": "abc"},
        "run_id": "run-1",
        "model_sha": "model",
        "distribution_sha": "dist"
    }
    with tempfile.TemporaryDirectory() as td:
        path = persist(base, "decision", Path(td))
        assert path.is_file()
        close = dict(base)
        close.pop("run_id"); close.pop("model_sha"); close.pop("distribution_sha")
        close["captured_at"] = "2026-09-03T23:04:00Z"
        close["quotes"] = [{"book_key": "draftkings", "market": "h2h", "price": -115, "retrieved_at": "2026-09-03T23:03:50Z"}]
        persist(close, "close", Path(td))
    print(json.dumps({"status": "SELF_TEST_OK"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("decision", "close"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.phase or not args.input:
        parser.error("--phase and --input are required")
    persist(json.loads(args.input.read_text()), args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
