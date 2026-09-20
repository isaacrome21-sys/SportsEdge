#!/usr/bin/env python3
"""Run frozen attempt-9 inference and the canonical Truth Gate in shadow only.

Consumes an acquired nflverse CSV and explicit two-sided quote records. Never
fits, spends an attempt, writes confirmation captures, or creates forward
promotion evidence. Report hashes provide traceability, not certification.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile

from scripts.capture_nfl_attempt9_prospective_predictions import capture
from sportsedge.sports.nfl.attempt9_model_p import model_probability, verify_model_p_artifact
from sportsedge.truth_gate import american_to_decimal, decide_bet

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SHA = "effa86bea2b1e9043cf0f4adffa007910a3d59f979f3ae07bcac15c6c4712d10"
MODEL_P_SHA = "868d02e16443969407cd15494c1429a4e664f38847e8e2f1366f5a66708ec92e"
SUPPORTED = {"spread": "spread", "total": "total", "alternate_spread": "spread", "alternate_total": "total"}


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _digest(value: dict) -> str:
    body = dict(value)
    body.pop("artifact_sha256", None)
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _quote_pair(quote: dict, game: dict, now: datetime) -> tuple[str, dict[str, float]]:
    market = SUPPORTED[quote["market"]]
    if quote.get("period") != "FULL_GAME":
        raise ValueError("FULL_GAME_REQUIRED")
    if quote.get("bookmaker") != "draftkings":
        raise ValueError("DRAFTKINGS_PAIR_REQUIRED")
    if _time(quote["kickoff_utc"]) != _time(game["kickoff_utc"]):
        raise ValueError("QUOTE_GAME_KICKOFF_MISMATCH")
    observed = _time(quote["observed_at"])
    if not 0 <= (now - observed).total_seconds() <= 180:
        raise ValueError("QUOTE_STALE_OR_FUTURE")
    if now >= _time(game["kickoff_utc"]):
        raise ValueError("GAME_ALREADY_STARTED")
    sides = quote["outcomes"]
    expected = {"home", "away"} if market == "spread" else {"over", "under"}
    if not isinstance(sides, list) or len(sides) != 2 or {s["selection"] for s in sides} != expected:
        raise ValueError("EXACT_OPPOSITE_PAIR_REQUIRED")
    line = quote["line"]
    if isinstance(line, bool) or not isinstance(line, (int, float)):
        raise ValueError("NUMERIC_LINE_REQUIRED")
    odds = {}
    for side in sides:
        if side.get("bookmaker") != quote["bookmaker"] or side.get("game_id") != game["game_id"]:
            raise ValueError("CROSS_BOOK_OR_GAME_PAIR")
        if side.get("observed_at") != quote["observed_at"] or side.get("period") != "FULL_GAME":
            raise ValueError("CROSS_SNAPSHOT_OR_PERIOD_PAIR")
        expected_line = -line if market == "spread" and side["selection"] == "away" else line
        if isinstance(side.get("line"), bool) or side.get("line") != expected_line:
            raise ValueError("OPPOSITE_LINE_MISMATCH")
        american_to_decimal(side["american_odds"])
        odds[side["selection"]] = side["american_odds"]
    return market, odds


def run_shadow(*, schedule: Path, quotes: list[dict], now: datetime, code_sha: str, root: Path = ROOT) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    if not isinstance(quotes, list):
        raise ValueError("QUOTE_LIST_REQUIRED")
    runtime = json.loads((root / "artifacts/football/nfl_attempt9_runtime_v1.json").read_text())
    artifact = json.loads((root / "artifacts/football/nfl_attempt9_model_p_v1.json").read_text())
    if _digest(runtime) != RUNTIME_SHA or runtime.get("artifact_sha256") != RUNTIME_SHA:
        raise ValueError("FROZEN_RUNTIME_IDENTITY_MISMATCH")
    if verify_model_p_artifact(artifact) != MODEL_P_SHA or artifact["runtime_artifact_sha256"] != RUNTIME_SHA:
        raise ValueError("FROZEN_MODEL_P_IDENTITY_MISMATCH")
    # Verify code bindings as well as artifact identity. Unrelated commits are OK.
    for name, expected in {
        "sportsedge/sports/nfl/attempt9_model_p.py": "b89b76b064ed863c6b78e6de7ca3838d7a6334bc",
        "scripts/build_nfl_attempt9_runtime_artifact.py": "113e887da78c0cfde199d71606626ee72baca9da",
    }.items():
        actual = subprocess.check_output(["git", "hash-object", str(root / name)], text=True).strip()
        if actual != expected:
            raise ValueError(f"FROZEN_CODE_DRIFT:{name}")
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        summary = capture(artifact=runtime, schedule=schedule, output_dir=output,
                          capture_code_git_sha=code_sha, captured=now, horizon_days=9)
        predictions = {p.stem: json.loads(p.read_text()) for p in output.glob("*.json")}
    surface = json.loads((root / "config/football_market_surface.json").read_text())
    floor = json.loads((root / "config/nfl_2026_prospective_governance_v1.json").read_text())["nfl_game_market_precommitted_thresholds"]["minimum_model_edge_probability_points"]
    rows = []
    for index, quote in enumerate(quotes):
        row = {"quote_index": index, "bet_status": "BLOCKED", "model_p": None, "stake": 0.0}
        try:
            row.update(game_id=quote["game_id"], market=quote["market"])
            if quote["market"] not in SUPPORTED:
                raise ValueError("UNSUPPORTED_BY_FROZEN_ATTEMPT9")
            game = predictions.get(quote["game_id"])
            if game is None:
                raise ValueError("NO_PREGAME_PREDICTION")
            market, odds = _quote_pair(quote, game, now)
            selection = quote["selection"]
            if selection not in odds:
                raise ValueError("SELECTION_NOT_IN_PAIR")
            forecast = game["raw_predicted_home_margin" if market == "spread" else "raw_predicted_game_total"]
            probability = model_probability(artifact, market=market, raw_prediction=forecast,
                                            line=quote["line"], selection=selection)
            inverse = {side: 1 / american_to_decimal(price) for side, price in odds.items()}
            fair = inverse[selection] / sum(inverse.values())
            decision = decide_bet(probability["model_p"], odds[selection],
                                  fair_market_probability=fair, bound=True, fresh=True,
                                  deployed=probability["deployed"], edge_floor=floor,
                                  push_probability=probability["push_probability"],
                                  kelly_multiplier=0.0, max_kelly_fraction=0.0)
            row.update(model_p=probability["model_p"], push_probability=probability["push_probability"],
                       raw_prediction=forecast, prediction_sha256=game["prediction_sha256"],
                       decision=asdict(decision), bet_status=decision.bet_status,
                       reason="PROSPECTIVE_PROMOTION_EVIDENCE_REQUIRED")
        except (KeyError, TypeError, ValueError) as exc:
            row["reason"] = str(exc)
        rows.append(row)
    coverage = [{"market": r["market"], "family": r["family"], "engines": r["engines"],
                 "state": "SHADOW_NONINTEGER_ONLY" if r["market"] in SUPPORTED else "UNSUPPORTED_BY_FROZEN_ATTEMPT9",
                 "official_authority": False} for r in surface["markets"]]
    return {"schema_version": "NFL_ATTEMPT9_SHADOW_REPORT_V1", "status": "SHADOW_ONLY_NOT_PROMOTION_EVIDENCE",
            "as_of_utc": now.isoformat(), "code_git_sha": code_sha,
            "runtime_artifact_sha256": RUNTIME_SHA, "model_p_artifact_sha256": MODEL_P_SHA,
            "schedule_snapshot_sha256": summary["schedule_snapshot_sha256"],
            "quotes_sha256": sha256(json.dumps(quotes, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "capture_summary": summary, "predictions": list(predictions.values()),
            "market_coverage": coverage, "rows": rows,
            "official_count": 0, "promotion_authority": False, "staking_authority": False,
            "forward_evidence_authority": False, "backfill_allowed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    # A wall-clock receipt is mandatory; the CLI cannot backdate a live run.
    now = datetime.now(timezone.utc)
    code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = run_shadow(schedule=args.schedule, quotes=json.loads(args.quotes.read_text()), now=now, code_sha=code_sha)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")
    print(json.dumps({"status": report["status"], "rows": len(report["rows"]), "official_count": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
