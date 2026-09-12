#!/usr/bin/env python3
"""Settle frozen NFL V2G prospective evidence from exact outcome snapshots.

The scorer consumes immutable prediction + PAPER-decision artifacts and, when
available, the independent DraftKings final-market binding. It cannot refit,
retune, promote, stake, or create Model_P.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POLICY_SCHEMA = "SPORTSEDGE_NFL_V2G_PROSPECTIVE_PAPER_EVALUATION_POLICY_V1"
PRED_SCHEMA = "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1"
PAPER_SCHEMA = "SPORTSEDGE_NFL_V2G_PAPER_DECISION_V1"
BINDING_SCHEMA = "SPORTSEDGE_NFL_V2G_MARKET_EVIDENCE_BINDING_V1"
OUT_SCHEMA = "SPORTSEDGE_NFL_V2G_PROSPECTIVE_SETTLEMENT_V1"


def die(code: str) -> None:
    raise SystemExit(code)


def parse_dt(value: Any, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"NFL_V2G_SETTLEMENT_TIMESTAMP_INVALID:{field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        die(f"NFL_V2G_SETTLEMENT_TIMESTAMP_TZ_REQUIRED:{field}")
    return dt.astimezone(timezone.utc)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        die(f"NFL_V2G_SETTLEMENT_JSON_OBJECT_REQUIRED:{path}")
    return value, sha256_bytes(raw)


def american_implied(price: float) -> float:
    p = float(price)
    if p == 0:
        die("NFL_V2G_SETTLEMENT_ZERO_AMERICAN_PRICE")
    return (-p) / ((-p) + 100.0) if p < 0 else 100.0 / (p + 100.0)


def american_profit(price: float) -> float:
    p = float(price)
    if p == 0:
        die("NFL_V2G_SETTLEMENT_ZERO_AMERICAN_PRICE")
    return 100.0 / (-p) if p < 0 else p / 100.0


def devig_two_way(price_a: float, price_b: float) -> tuple[float, float]:
    a, b = american_implied(price_a), american_implied(price_b)
    denom = a + b
    if denom <= 0:
        die("NFL_V2G_SETTLEMENT_DEVIG_INVALID")
    return a / denom, b / denom


def validate_inputs(policy: dict[str, Any], pred: dict[str, Any], paper: dict[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA:
        die("NFL_V2G_SETTLEMENT_POLICY_SCHEMA_INVALID")
    if pred.get("schema_version") != PRED_SCHEMA:
        die("NFL_V2G_SETTLEMENT_PREDICTION_SCHEMA_INVALID")
    if paper.get("schema_version") != PAPER_SCHEMA:
        die("NFL_V2G_SETTLEMENT_PAPER_SCHEMA_INVALID")
    if pred.get("candidate_id") != policy.get("candidate_id") or paper.get("candidate_id") != policy.get("candidate_id"):
        die("NFL_V2G_SETTLEMENT_CANDIDATE_MISMATCH")
    artifact = policy.get("frozen_research_artifact_sha256")
    if pred.get("artifact_sha256") != artifact or paper.get("artifact_sha256") != artifact:
        die("NFL_V2G_SETTLEMENT_ARTIFACT_MISMATCH")
    if paper.get("prediction_sha256") != pred.get("prediction_sha256"):
        die("NFL_V2G_SETTLEMENT_PREDICTION_BINDING_MISMATCH")
    if pred.get("market_prices_consumed") is not False or paper.get("market_prices_consumed_by_model") is not False:
        die("NFL_V2G_SETTLEMENT_MARKET_LEAKAGE")
    kickoff = parse_dt(pred.get("kickoff_utc"), "kickoff")
    if parse_dt(pred.get("captured_at_utc"), "prediction_captured_at") >= kickoff:
        die("NFL_V2G_SETTLEMENT_PREDICTION_NOT_PREGAME")
    if parse_dt(paper.get("decision_generated_at_utc"), "paper_decision_at") >= kickoff:
        die("NFL_V2G_SETTLEMENT_PAPER_NOT_PREGAME")
    for obj, label in ((pred, "PREDICTION"), (paper, "PAPER")):
        for key in ("promotion_authority", "may_create_model_p", "market_eligibility_changed", "official_status_granted"):
            if obj.get(key) is not False:
                die(f"NFL_V2G_SETTLEMENT_{label}_AUTHORITY_INVALID:{key}")


def parse_score(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not number.is_integer():
        return None
    return int(number)


def find_outcome(csv_path: Path, pred: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    raw = csv_path.read_bytes()
    source_sha = sha256_bytes(raw)
    text = raw.decode("utf-8-sig").splitlines()
    matches = []
    for row in csv.DictReader(text):
        gid = str(row.get("game_id") or "").strip()
        exact = gid == str(pred.get("game_id") or "")
        fallback = (
            str(row.get("season") or "") == str(pred.get("season") or "")
            and str(row.get("week") or "") == str(pred.get("week") or "")
            and str(row.get("home_team") or "").strip() == str(pred.get("home_team") or "")
            and str(row.get("away_team") or "").strip() == str(pred.get("away_team") or "")
        )
        if exact or fallback:
            matches.append(row)
    if len(matches) > 1:
        die(f"NFL_V2G_SETTLEMENT_OUTCOME_MATCH_AMBIGUOUS:{pred.get('game_id')}")
    if not matches:
        return None, source_sha
    row = matches[0]
    home_score = parse_score(row.get("home_score"))
    away_score = parse_score(row.get("away_score"))
    if home_score is None or away_score is None:
        return None, source_sha
    return {
        "game_id": pred["game_id"],
        "home_team": pred["home_team"],
        "away_team": pred["away_team"],
        "home_score": home_score,
        "away_score": away_score,
        "home_margin": home_score - away_score,
        "total_points": home_score + away_score,
    }, source_sha


def model_spread(distribution: list[dict[str, Any]], home_point: float) -> dict[str, float]:
    home = away = push = 0.0
    for row in distribution:
        w = float(row["weight"])
        value = float(row["margin"]) + float(home_point)
        if value > 0:
            home += w
        elif value < 0:
            away += w
        else:
            push += w
    denom = home + away
    if denom <= 0:
        die("NFL_V2G_SETTLEMENT_SPREAD_NONPUSH_MASS_ZERO")
    return {"home": home / denom, "away": away / denom, "push": push}


def model_total(distribution: list[dict[str, Any]], point: float) -> dict[str, float]:
    over = under = push = 0.0
    for row in distribution:
        w = float(row["weight"])
        total = float(row["total"])
        if total > point:
            over += w
        elif total < point:
            under += w
        else:
            push += w
    denom = over + under
    if denom <= 0:
        die("NFL_V2G_SETTLEMENT_TOTAL_NONPUSH_MASS_ZERO")
    return {"over": over / denom, "under": under / denom, "push": push}


def binary_scores(p: float, y: int) -> tuple[float, float]:
    q = min(max(float(p), 1e-12), 1.0 - 1e-12)
    return -math.log(q if y else 1.0 - q), (q - float(y)) ** 2


def validate_binding(binding: dict[str, Any] | None, pred: dict[str, Any]) -> None:
    if binding is None:
        return
    if binding.get("schema_version") != BINDING_SCHEMA:
        die("NFL_V2G_SETTLEMENT_BINDING_SCHEMA_INVALID")
    if binding.get("game_id") != pred.get("game_id"):
        die("NFL_V2G_SETTLEMENT_BINDING_GAME_MISMATCH")
    if binding.get("candidate_id") != pred.get("candidate_id"):
        die("NFL_V2G_SETTLEMENT_BINDING_CANDIDATE_MISMATCH")
    if binding.get("prediction", {}).get("prediction_sha256") != pred.get("prediction_sha256"):
        die("NFL_V2G_SETTLEMENT_BINDING_PREDICTION_MISMATCH")
    if binding.get("market_prices_consumed_by_model") is not False:
        die("NFL_V2G_SETTLEMENT_BINDING_MARKET_LEAKAGE")
    for key in ("promotion_authority", "may_create_model_p", "market_eligibility_changed", "official_status_granted"):
        if binding.get(key) is not False:
            die(f"NFL_V2G_SETTLEMENT_BINDING_AUTHORITY_INVALID:{key}")


def predictive_market(market: str, pred: dict[str, Any], binding: dict[str, Any] | None, outcome: dict[str, Any]) -> dict[str, Any]:
    if binding is None:
        return {"status": "INCONCLUSIVE_MISSING_CAPTURE"}
    final_market = ((binding.get("final") or {}).get("market") or {}).get(market)
    if not isinstance(final_market, dict) or final_market.get("status") != "OK":
        return {"status": "INCONCLUSIVE_MISSING_CAPTURE"}

    if market == "spread":
        point = float(final_market["home_point"])
        actual = float(outcome["home_margin"]) + point
        if actual == 0:
            return {"status": "NOT_SCORED_PUSH", "closing_line": point}
        y = 1 if actual > 0 else 0
        model = model_spread(pred["score_distribution"], point)
        model_p = model["home"]
        mkt_home, _ = devig_two_way(float(final_market["home_price"]), float(final_market["away_price"]))
        market_p = mkt_home
        orientation = "HOME_COVER"
    elif market == "total":
        point = float(final_market["point"])
        actual = float(outcome["total_points"]) - point
        if actual == 0:
            return {"status": "NOT_SCORED_PUSH", "closing_line": point}
        y = 1 if actual > 0 else 0
        model = model_total(pred["score_distribution"], point)
        model_p = model["over"]
        mkt_over, _ = devig_two_way(float(final_market["over_price"]), float(final_market["under_price"]))
        market_p = mkt_over
        orientation = "OVER"
    else:
        die(f"NFL_V2G_SETTLEMENT_MARKET_INVALID:{market}")

    model_ll, model_brier = binary_scores(model_p, y)
    market_ll, market_brier = binary_scores(market_p, y)
    return {
        "status": "SCORED",
        "orientation": orientation,
        "closing_line": point,
        "outcome": y,
        "model_probability": model_p,
        "closing_no_vig_probability": market_p,
        "model_log_loss": model_ll,
        "closing_market_log_loss": market_ll,
        "model_brier": model_brier,
        "closing_market_brier": market_brier,
        "model_beats_close_log_loss": model_ll < market_ll,
    }


def paper_market(market: str, paper: dict[str, Any], binding: dict[str, Any] | None, outcome: dict[str, Any]) -> dict[str, Any]:
    decision = (paper.get("decisions") or {}).get(market) or {}
    if decision.get("status") != "PAPER_CANDIDATE":
        return {"status": "NO_PAPER_CANDIDATE"}
    selection = decision["selection"]
    side = selection["side"]
    line = float(selection["line"])
    price = float(selection["price"])

    if market == "spread":
        margin = float(outcome["home_margin"])
        adjusted = margin + line if side == "home" else -margin + line
    else:
        total = float(outcome["total_points"])
        adjusted = total - line if side == "over" else line - total
    result = "WIN" if adjusted > 0 else "LOSS" if adjusted < 0 else "PUSH"
    profit = american_profit(price) if result == "WIN" else -1.0 if result == "LOSS" else 0.0

    clv = {"status": "INCONCLUSIVE_MISSING_CAPTURE", "line_clv": None, "probability_clv": None}
    if binding is not None:
        final_market = ((binding.get("final") or {}).get("market") or {}).get(market)
        if isinstance(final_market, dict) and final_market.get("status") == "OK":
            opener_market_p = float(selection["market_no_vig_probability"])
            if market == "spread":
                close_line = float(final_market["home_point"] if side == "home" else final_market["away_point"])
                close_price = float(final_market["home_price"] if side == "home" else final_market["away_price"])
                home_p, away_p = devig_two_way(float(final_market["home_price"]), float(final_market["away_price"]))
                close_market_p = home_p if side == "home" else away_p
                line_clv = line - close_line
            else:
                close_line = float(final_market["point"])
                close_price = float(final_market["over_price"] if side == "over" else final_market["under_price"])
                over_p, under_p = devig_two_way(float(final_market["over_price"]), float(final_market["under_price"]))
                close_market_p = over_p if side == "over" else under_p
                line_clv = close_line - line if side == "over" else line - close_line
            same_line = abs(close_line - line) <= 1e-9
            clv = {
                "status": "COMPARABLE_SAME_LINE" if same_line else "NOT_COMPARABLE_LINE_CHANGED",
                "closing_line": close_line,
                "closing_price": close_price,
                "closing_no_vig_probability": close_market_p,
                "line_clv": line_clv,
                "probability_clv": close_market_p - opener_market_p if same_line else None,
            }

    return {
        "status": "SETTLED_PAPER_CANDIDATE",
        "side": side,
        "selection": selection.get("selection"),
        "opener_line": line,
        "opener_price": price,
        "edge_probability": selection.get("edge_probability"),
        "expected_value_units_per_unit": selection.get("expected_value_units_per_unit"),
        "result": result,
        "after_vig_profit_units": profit,
        "clv": clv,
    }


def build(pred_path: Path, paper_path: Path, binding_path: Path | None, games_csv: Path, policy_path: Path, settled_at_utc: str) -> dict[str, Any]:
    pred, pred_file_sha = load_json(pred_path)
    paper, paper_file_sha = load_json(paper_path)
    policy, policy_file_sha = load_json(policy_path)
    validate_inputs(policy, pred, paper)
    binding = binding_file_sha = None
    if binding_path is not None and binding_path.exists():
        binding, binding_file_sha = load_json(binding_path)
        validate_binding(binding, pred)
    outcome, source_sha = find_outcome(games_csv, pred)
    settled_at = parse_dt(settled_at_utc, "settled_at_utc")
    if outcome is None:
        return {
            "schema_version": OUT_SCHEMA,
            "status": "OUTCOME_NOT_FINAL",
            "game_id": pred["game_id"],
            "outcome_source_snapshot_sha256": source_sha,
            "promotion_authority": False,
            "may_create_model_p": False,
            "official_status_granted": False,
        }
    kickoff = parse_dt(pred["kickoff_utc"], "kickoff")
    if settled_at <= kickoff:
        die("NFL_V2G_SETTLEMENT_BEFORE_KICKOFF")

    predictive = {
        "spread": predictive_market("spread", pred, binding, outcome),
        "total": predictive_market("total", pred, binding, outcome),
    }
    paper_results = {
        "spread": paper_market("spread", paper, binding, outcome),
        "total": paper_market("total", paper, binding, outcome),
    }
    missing_capture = any(v.get("status") == "INCONCLUSIVE_MISSING_CAPTURE" for v in predictive.values())
    output: dict[str, Any] = {
        "schema_version": OUT_SCHEMA,
        "status": "SETTLED_INCONCLUSIVE_MISSING_CAPTURE" if missing_capture else "SETTLED_PROSPECTIVE_EVIDENCE",
        "game_id": pred["game_id"],
        "candidate_id": pred["candidate_id"],
        "artifact_sha256": pred["artifact_sha256"],
        "kickoff_utc": pred["kickoff_utc"],
        "settled_at_utc": settled_at.isoformat(),
        "prediction_sha256": pred.get("prediction_sha256"),
        "paper_decision_sha256": paper.get("paper_decision_sha256"),
        "prediction_file_sha256": pred_file_sha,
        "paper_file_sha256": paper_file_sha,
        "binding_file_sha256": binding_file_sha,
        "policy_file_sha256": policy_file_sha,
        "outcome_source_snapshot_sha256": source_sha,
        "outcome": outcome,
        "predictive_evaluation": predictive,
        "paper_evaluation": paper_results,
        "market_prices_consumed_by_model": False,
        "paper_research_only": True,
        "promotion_authority": False,
        "may_create_model_p": False,
        "market_eligibility_changed": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }
    output["settlement_sha256"] = sha256_bytes(canonical_bytes({k: v for k, v in output.items() if k != "settlement_sha256"}))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--paper-decision", type=Path, required=True)
    parser.add_argument("--market-binding", type=Path)
    parser.add_argument("--games-csv", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--settled-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.prediction, args.paper_decision, args.market_binding, args.games_csv, args.policy, args.settled_at_utc)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and args.output.read_text(encoding="utf-8") != encoded:
        die(f"NFL_V2G_SETTLEMENT_REFUSING_OVERWRITE:{args.output}")
    args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({"game_id": result["game_id"], "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
