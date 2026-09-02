#!/usr/bin/env python3
"""Persist immutable MLB V8 decision/close evidence records.

Decision evidence is the exact canonical-machine quote/model state used at the
standardized forward decision time. Close evidence is a separately captured quote
state. Neither phase can overwrite or relabel the other.
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
    text = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _hex(value: Any, *, lengths: tuple[int, ...]) -> bool:
    text = str(value or "").strip().lower()
    if len(text) not in lengths:
        return False
    try:
        int(text, 16)
    except ValueError:
        return False
    return True


def validate(payload: dict[str, Any], phase: str) -> None:
    if phase not in {"decision", "close"}:
        raise ValueError("unsupported V8 evidence phase")
    required = ["game_id", "first_pitch_at", "captured_at", "quotes", "source_provenance"]
    if phase == "decision":
        required += ["run_id", "model_sha", "distribution_sha", "decision_rows"]
    missing = [key for key in required if payload.get(key) in (None, "", [], {})]
    if missing:
        raise ValueError("missing required V8 evidence fields: " + ",".join(missing))

    first_pitch = parse_ts(str(payload["first_pitch_at"]))
    captured = parse_ts(str(payload["captured_at"]))
    if captured >= first_pitch:
        raise ValueError("V8 pregame evidence must be captured before first pitch")

    provenance = payload.get("source_provenance")
    if not isinstance(provenance, dict) or not provenance:
        raise ValueError("source_provenance must be a non-empty object")

    quotes = payload.get("quotes")
    if not isinstance(quotes, list) or not quotes:
        raise ValueError("quotes must be a non-empty list")
    for quote in quotes:
        if not isinstance(quote, dict):
            raise ValueError("quote must be an object")
        for key in ("book_key", "market", "price", "retrieved_at"):
            if quote.get(key) in (None, ""):
                raise ValueError(f"quote missing {key}")
        retrieved = parse_ts(str(quote["retrieved_at"]))
        if retrieved > captured:
            raise ValueError("quote retrieved_at cannot be after captured_at")
        if retrieved >= first_pitch:
            raise ValueError("post-first-pitch quote cannot enter pregame V8 evidence")

    if phase == "decision":
        if not _hex(payload["model_sha"], lengths=(40, 64)):
            raise ValueError("model_sha must be an exact git/model SHA")
        if not _hex(payload["distribution_sha"], lengths=(64,)):
            raise ValueError("distribution_sha must be sha256")
        rows = payload.get("decision_rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("decision_rows must be non-empty")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("decision row must be an object")
            for key in ("market", "model_p", "distribution_sha256", "model_input_hash"):
                if row.get(key) in (None, ""):
                    raise ValueError(f"decision row missing {key}")
            if not _hex(row["distribution_sha256"], lengths=(64,)):
                raise ValueError("decision row distribution_sha256 invalid")


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
    dsha = "d" * 64
    base = {
        "game_id": "123",
        "first_pitch_at": "2026-09-03T23:05:00Z",
        "captured_at": "2026-09-03T22:00:00Z",
        "quotes": [{"book_key": "draftkings", "market": "MONEYLINE", "price": -120, "retrieved_at": "2026-09-03T21:59:50Z"}],
        "source_provenance": {"provider": "SPORTSEDGE_CANONICAL_MLB_MACHINE", "card_sha256": "c" * 64},
        "run_id": "run-1",
        "model_sha": "a" * 40,
        "distribution_sha": dsha,
        "decision_rows": [{"market": "MONEYLINE", "model_p": 0.55, "distribution_sha256": dsha, "model_input_hash": "input"}],
    }
    with tempfile.TemporaryDirectory() as td:
        path = persist(base, "decision", Path(td))
        assert path.is_file()
        close = dict(base)
        for key in ("run_id", "model_sha", "distribution_sha", "decision_rows"):
            close.pop(key)
        close["captured_at"] = "2026-09-03T23:04:00Z"
        close["quotes"] = [{"book_key": "draftkings", "market": "MONEYLINE", "price": -115, "retrieved_at": "2026-09-03T23:03:50Z"}]
        persist(close, "close", Path(td))
        bad = dict(base)
        bad["captured_at"] = bad["first_pitch_at"]
        try:
            persist(bad, "decision", Path(td))
        except ValueError:
            pass
        else:
            raise AssertionError("post-start decision was not rejected")
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
