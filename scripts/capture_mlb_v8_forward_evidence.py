#!/usr/bin/env python3
"""Persist immutable MLB V8 decision/close evidence and terminal capture status."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path("artifacts/mlb_v8_forward")
STATUS_ROOT = Path("artifacts/mlb_v8_status")
POLICY = Path("config/mlb_v8_evidence_policy.json")
DECISION_TARGET_MIN = 30.0
DECISION_TOLERANCE_MIN = 6.0
DECISION_TOLERANCE_DIRECTION = "EARLY_ONLY_AT_OR_BEFORE_TARGET"


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


def _actual_minutes_before_first_pitch(payload: dict[str, Any]) -> float:
    first_pitch = parse_ts(str(payload["first_pitch_at"]))
    captured = parse_ts(str(payload["captured_at"]))
    return (first_pitch - captured).total_seconds() / 60.0


def _assert_policy_binding() -> None:
    policy = json.loads(POLICY.read_text())
    decision = policy.get("decision_capture") or {}
    if float(decision.get("target_minutes_before_first_pitch", -1)) != DECISION_TARGET_MIN:
        raise RuntimeError("code/policy decision target drift")
    if float(decision.get("tolerance_minutes", -1)) != DECISION_TOLERANCE_MIN:
        raise RuntimeError("code/policy decision tolerance drift")
    if decision.get("tolerance_direction") != DECISION_TOLERANCE_DIRECTION:
        raise RuntimeError("code/policy decision tolerance direction drift")


def validate(payload: dict[str, Any], phase: str) -> None:
    _assert_policy_binding()
    if phase not in {"decision", "close"}:
        raise ValueError("unsupported V8 evidence phase")
    required = ["game_id", "first_pitch_at", "captured_at", "quotes", "source_provenance", "minutes_before_first_pitch"]
    if phase == "decision":
        required += [
            "run_id", "model_sha", "distribution_sha", "decision_rows",
            "decision_target_minutes", "decision_target_qualified", "decision_tolerance_direction",
        ]
    missing = [key for key in required if payload.get(key) in (None, "", [], {}) and payload.get(key) is not False]
    if missing:
        raise ValueError("missing required V8 evidence fields: " + ",".join(missing))

    first_pitch = parse_ts(str(payload["first_pitch_at"]))
    captured = parse_ts(str(payload["captured_at"]))
    if captured >= first_pitch:
        raise ValueError("V8 pregame evidence must be captured before first pitch")
    actual_minutes = _actual_minutes_before_first_pitch(payload)
    if abs(actual_minutes - float(payload["minutes_before_first_pitch"])) > 0.02:
        raise ValueError("minutes_before_first_pitch does not match exact timestamps")

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
        target = float(payload["decision_target_minutes"])
        if target != DECISION_TARGET_MIN:
            raise ValueError("unexpected V8 decision target")
        if payload.get("decision_tolerance_direction") != DECISION_TOLERANCE_DIRECTION:
            raise ValueError("decision tolerance direction must be one-sided at-or-before")
        timing_ok = actual_minutes >= target and (actual_minutes - target) <= DECISION_TOLERANCE_MIN
        if not bool(payload.get("decision_target_qualified")) or not timing_ok:
            raise ValueError("late/out-of-window capture cannot be persisted as T-30 decision evidence")
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


def write_terminal_status(
    *, plan: dict[str, Any], run_id: str, git_sha: str, model_outcome: str,
    capture_outcome: str, root: Path = STATUS_ROOT, recorded_at: datetime | None = None,
) -> Path:
    _assert_policy_binding()
    now = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    games = plan.get("games") or []
    game_statuses: list[dict[str, Any]] = []
    for game in games:
        phases = list(game.get("phases") or [])
        late = str(game.get("decision_timing_status") or "") == "LATE_CAPTURE"
        if late and "decision" not in phases:
            capture_status = "LATE_CAPTURE"
        elif model_outcome == "success" and capture_outcome == "success" and phases:
            capture_status = "CAPTURED"
        else:
            capture_status = "MISSED_OR_BLOCKED"
        game_statuses.append({
            "game_id": str(game.get("game_id") or ""),
            "minutes_before_first_pitch": game.get("minutes_before_first_pitch"),
            "phases": phases,
            "decision_target_qualified": bool(game.get("decision_target_qualified")),
            "capture_status": capture_status,
        })

    noncaptured = [g for g in game_statuses if g["capture_status"] != "CAPTURED"]
    if noncaptured:
        status = "MISSED_OR_BLOCKED"
        details = sorted({str(g["capture_status"]) for g in noncaptured})
        status_detail = "+".join(details)
    elif game_statuses and model_outcome == "success" and capture_outcome == "success":
        status = "CAPTURED"
        status_detail = "ALL_TARGET_EVENTS_CAPTURED"
    else:
        status = "MISSED_OR_BLOCKED"
        status_detail = "NO_SUCCESSFUL_TARGET_CAPTURE"

    payload = {
        "schema": "MLB_V8_FORWARD_STATUS_V1",
        "run_id": run_id,
        "recorded_at_utc": now.isoformat(),
        "git_sha": git_sha,
        "slate_date_ct": plan.get("slate_date_ct"),
        "target_games": games,
        "target_game_statuses": game_statuses,
        "model_outcome": model_outcome,
        "capture_outcome": capture_outcome,
        "status": status,
        "status_detail": status_detail,
    }
    root.mkdir(parents=True, exist_ok=True)
    safe_run = run_id.replace("/", "_").replace(":", "_")
    destination = root / f"status_{safe_run}.json"
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    if destination.exists() and destination.read_bytes() != encoded:
        raise RuntimeError("immutable V8 status collision")
    destination.write_bytes(encoded)
    print(json.dumps(payload, sort_keys=True))
    return destination


def self_test() -> int:
    import tempfile
    _assert_policy_binding()
    dsha = "d" * 64
    base = {
        "game_id": "123", "first_pitch_at": "2026-09-03T23:05:00Z", "captured_at": "2026-09-03T22:35:00Z",
        "minutes_before_first_pitch": 30.0,
        "quotes": [{"book_key": "draftkings", "market": "MONEYLINE", "price": -120, "retrieved_at": "2026-09-03T22:34:50Z"}],
        "source_provenance": {"provider": "SPORTSEDGE_CANONICAL_MLB_MACHINE", "card_sha256": "c" * 64},
        "run_id": "run-1", "model_sha": "a" * 40, "distribution_sha": dsha,
        "decision_target_minutes": 30.0, "decision_target_qualified": True,
        "decision_tolerance_direction": DECISION_TOLERANCE_DIRECTION,
        "decision_rows": [{"market": "MONEYLINE", "model_p": 0.55, "distribution_sha256": dsha, "model_input_hash": "input"}],
    }
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assert persist(base, "decision", root / "evidence").is_file()
        close = dict(base)
        for key in ("run_id", "model_sha", "distribution_sha", "decision_rows", "decision_target_minutes", "decision_target_qualified", "decision_tolerance_direction"):
            close.pop(key)
        close["captured_at"] = "2026-09-03T23:04:00Z"
        close["minutes_before_first_pitch"] = 1.0
        close["quotes"] = [{"book_key": "draftkings", "market": "MONEYLINE", "price": -115, "retrieved_at": "2026-09-03T23:03:50Z"}]
        persist(close, "close", root / "evidence")

        late = dict(base)
        late["captured_at"] = "2026-09-03T22:41:00Z"
        late["minutes_before_first_pitch"] = 24.0
        late["decision_target_qualified"] = False
        try:
            persist(late, "decision", root / "evidence")
        except ValueError:
            pass
        else:
            raise AssertionError("late T-24 capture was persisted as T-30 decision evidence")

        late_plan = {"slate_date_ct": "2026-09-03", "games": [{"game_id": "123", "phases": [], "minutes_before_first_pitch": 24.0, "decision_timing_status": "LATE_CAPTURE", "decision_target_qualified": False}]}
        status_path = write_terminal_status(
            plan=late_plan, run_id="local:1", git_sha="a" * 40, model_outcome="not-run", capture_outcome="not-run",
            root=root / "status", recorded_at=datetime(2026, 9, 3, 22, 41, tzinfo=timezone.utc),
        )
        status = json.loads(status_path.read_text())
        assert status["status"] == "MISSED_OR_BLOCKED"
        assert status["status_detail"] == "LATE_CAPTURE"
        assert status["target_game_statuses"][0]["capture_status"] == "LATE_CAPTURE"
    print(json.dumps({"status": "SELF_TEST_OK", "late_decision_rejected": True, "status_parity": True, "policy_binding": True}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("decision", "close"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--git-sha")
    parser.add_argument("--model-outcome", default="not-run")
    parser.add_argument("--capture-outcome", default="not-run")
    parser.add_argument("--status-root", type=Path, default=STATUS_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.write_status:
        if not all((args.plan, args.run_id, args.git_sha)):
            parser.error("--write-status requires --plan --run-id --git-sha")
        write_terminal_status(
            plan=json.loads(args.plan.read_text()), run_id=str(args.run_id), git_sha=str(args.git_sha),
            model_outcome=str(args.model_outcome), capture_outcome=str(args.capture_outcome), root=args.status_root,
        )
        return 0
    if not args.phase or not args.input:
        parser.error("--phase and --input are required")
    persist(json.loads(args.input.read_text()), args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
