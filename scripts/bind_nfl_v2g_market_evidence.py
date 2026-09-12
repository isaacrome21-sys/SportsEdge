#!/usr/bin/env python3
"""Bind immutable NFL V2G prospective predictions to independent market captures.

This is downstream evidence plumbing only. It never creates or alters Model_P and
never feeds sportsbook prices back into V2G.

Fail-closed rules:
- prediction must be NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1 and market-blind;
- opener/final captures must be DraftKings spreads+totals and lock MATCH/CREATED;
- matching is explicit by canonical team code plus kickoff time, never fuzzy;
- opener and final must both be pre-kickoff;
- spread and total readiness are evaluated independently and each requires a
  valid paired opener + final market row;
- missing evidence is never invented or backfilled;
- output grants no promotion, Model_P, Truth Gate PASS, staking, or OFFICIAL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "SPORTSEDGE_NFL_V2G_MARKET_EVIDENCE_BINDING_V1"
PRED_SCHEMA = "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1"
READY = "READY_FOR_PROSPECTIVE_EVALUATION"
PARTIAL = "PARTIAL_MARKET_EVIDENCE"
INCONCLUSIVE = "INCONCLUSIVE_MISSING_CAPTURE"

TEAM_CODE_BY_NAME = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def load_json(path: Path):
    raw = path.read_bytes()
    return json.loads(raw), sha256_bytes(raw)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def canonical_capture_team(name: str) -> str:
    try:
        return TEAM_CODE_BY_NAME[name]
    except KeyError as exc:
        raise SystemExit(f"NFL_V2G_UNKNOWN_CAPTURE_TEAM:{name}") from exc


def validate_prediction(pred: dict) -> None:
    if pred.get("schema_version") != PRED_SCHEMA:
        raise SystemExit("NFL_V2G_PREDICTION_SCHEMA_INVALID")
    if pred.get("market_prices_consumed") is not False:
        raise SystemExit("NFL_V2G_PREDICTION_MARKET_LEAKAGE")
    for key in (
        "promotion_authority", "may_create_model_p", "market_eligibility_changed",
        "official_status_granted",
    ):
        if pred.get(key) is not False:
            raise SystemExit(f"NFL_V2G_PREDICTION_AUTHORITY_INVALID:{key}")
    if parse_dt(pred["captured_at_utc"]) >= parse_dt(pred["kickoff_utc"]):
        raise SystemExit("NFL_V2G_PREDICTION_NOT_PREGAME")


def capture_is_eligible(capture: dict, kind: str) -> None:
    if capture.get("capture_kind") != kind:
        raise SystemExit(f"NFL_V2G_CAPTURE_KIND_INVALID:{kind}")
    if capture.get("book") != "draftkings":
        raise SystemExit("NFL_V2G_CAPTURE_BOOK_INVALID")
    if set(capture.get("markets") or []) != {"spreads", "totals"}:
        raise SystemExit("NFL_V2G_CAPTURE_MARKETS_INVALID")
    lock = str(capture.get("lock_status") or "")
    if lock not in {"MATCH", "LOCK_CREATED"}:
        raise SystemExit(f"NFL_V2G_CAPTURE_LOCK_INVALID:{lock}")


def match_game(pred: dict, capture: dict) -> dict | None:
    kickoff = parse_dt(pred["kickoff_utc"])
    matches = []
    for row in capture.get("games") or []:
        away = canonical_capture_team(row.get("away_team", ""))
        home = canonical_capture_team(row.get("home_team", ""))
        if away != pred["away_team"] or home != pred["home_team"]:
            continue
        commence = parse_dt(row["commence_time"])
        if abs((commence - kickoff).total_seconds()) > 60:
            continue
        matches.append(row)
    if len(matches) > 1:
        raise SystemExit(f"NFL_V2G_AMBIGUOUS_MARKET_MATCH:{pred['game_id']}")
    return matches[0] if matches else None


def market_payload(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "event_id": row.get("event_id"),
        "book": row.get("book"),
        "book_last_update": row.get("book_last_update"),
        "commence_time": row.get("commence_time"),
        "spread": row.get("spread"),
        "total": row.get("total"),
    }


def market_ready(row: dict | None, key: str) -> bool:
    return bool(row and isinstance(row.get(key), dict) and row[key].get("status") == "OK")


def paired_market_status(opener_row: dict | None, final_row: dict | None, key: str) -> dict:
    missing = []
    if not market_ready(opener_row, key):
        missing.append(f"opener_{key}")
    if not market_ready(final_row, key):
        missing.append(f"final_{key}")
    return {
        "status": READY if not missing else INCONCLUSIVE,
        "missing_components": missing,
    }


def bind(pred_path: Path, opener_path: Path | None, final_paths: list[Path]) -> dict:
    pred, pred_file_sha = load_json(pred_path)
    validate_prediction(pred)
    kickoff = parse_dt(pred["kickoff_utc"])

    opener_capture = opener_row = None
    opener_file_sha = None
    opener_source = None
    if opener_path and opener_path.exists():
        opener_capture, opener_file_sha = load_json(opener_path)
        capture_is_eligible(opener_capture, "OPENER")
        retrieved = parse_dt(opener_capture["retrieved_at_utc"])
        if retrieved >= kickoff:
            raise SystemExit("NFL_V2G_OPENER_NOT_PREGAME")
        opener_row = match_game(pred, opener_capture)
        opener_source = str(opener_path)

    final_match = None
    final_file_sha = None
    final_retrieved = None
    final_source = None
    for path in sorted(final_paths):
        capture, file_sha = load_json(path)
        capture_is_eligible(capture, "FINAL")
        row = match_game(pred, capture)
        if row is None:
            continue
        retrieved = parse_dt(capture["retrieved_at_utc"])
        if retrieved >= kickoff:
            raise SystemExit("NFL_V2G_FINAL_AFTER_KICKOFF")
        if final_match is not None:
            raise SystemExit(f"NFL_V2G_MULTIPLE_FINAL_MATCHES:{pred['game_id']}")
        final_match = row
        final_file_sha = file_sha
        final_retrieved = capture["retrieved_at_utc"]
        final_source = str(path)

    market_status = {
        "spread": paired_market_status(opener_row, final_match, "spread"),
        "total": paired_market_status(opener_row, final_match, "total"),
    }
    ready_count = sum(v["status"] == READY for v in market_status.values())
    if ready_count == 2:
        status = READY
    elif ready_count == 1:
        status = PARTIAL
    else:
        status = INCONCLUSIVE

    missing_components = sorted({
        item
        for details in market_status.values()
        for item in details["missing_components"]
    })
    script_bytes = Path(__file__).read_bytes()
    return {
        "schema_version": SCHEMA,
        "status": status,
        "market_status": market_status,
        "missing_components": missing_components,
        "game_id": pred["game_id"],
        "candidate_id": pred["candidate_id"],
        "away_team": pred["away_team"],
        "home_team": pred["home_team"],
        "kickoff_utc": pred["kickoff_utc"],
        "binding_code_git_blob_sha1": git_blob_sha1(script_bytes),
        "prediction": {
            "path": str(pred_path),
            "file_sha256": pred_file_sha,
            "prediction_sha256": pred.get("prediction_sha256"),
            "artifact_sha256": pred.get("artifact_sha256"),
            "implementation_commit_sha": pred.get("implementation_commit_sha"),
            "capture_code_git_sha": pred.get("capture_code_git_sha"),
            "schedule_snapshot_sha256": pred.get("schedule_snapshot_sha256"),
            "captured_at_utc": pred.get("captured_at_utc"),
        },
        "opener": {
            "path": opener_source,
            "capture_file_sha256": opener_file_sha,
            "retrieved_at_utc": opener_capture.get("retrieved_at_utc") if opener_capture else None,
            "market": market_payload(opener_row),
        },
        "final": {
            "path": final_source,
            "capture_file_sha256": final_file_sha,
            "retrieved_at_utc": final_retrieved,
            "market": market_payload(final_match),
        },
        "market_prices_consumed_by_model": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "market_eligibility_changed": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--opener", type=Path)
    parser.add_argument("--final-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    finals = list(args.final_dir.glob("*.json")) if args.final_dir.exists() else []
    result = bind(args.prediction, args.opener, finals)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output.exists() and args.output.read_text(encoding="utf-8") != encoded:
        raise SystemExit(f"NFL_V2G_REFUSING_EVIDENCE_OVERWRITE:{args.output}")
    args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({
        "game_id": result["game_id"],
        "status": result["status"],
        "market_status": result["market_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
