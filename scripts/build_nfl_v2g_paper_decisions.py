#!/usr/bin/env python3
"""Build immutable PAPER decisions from frozen V2G predictions + opener prices."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

POLICY_SCHEMA = "SPORTSEDGE_NFL_V2G_PROSPECTIVE_PAPER_EVALUATION_POLICY_V1"
PRED_SCHEMA = "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1"
OUT_SCHEMA = "SPORTSEDGE_NFL_V2G_PAPER_DECISION_V1"

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


def die(code: str) -> None:
    raise SystemExit(code)


def parse_dt(value: Any, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"NFL_V2G_PAPER_TIMESTAMP_INVALID:{field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        die(f"NFL_V2G_PAPER_TIMESTAMP_TZ_REQUIRED:{field}")
    return dt.astimezone(timezone.utc)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        die(f"NFL_V2G_PAPER_JSON_OBJECT_REQUIRED:{path}")
    return value, sha256_bytes(raw)


def american_implied(price: float) -> float:
    p = float(price)
    if p == 0:
        die("NFL_V2G_PAPER_ZERO_AMERICAN_PRICE")
    return (-p) / ((-p) + 100.0) if p < 0 else 100.0 / (p + 100.0)


def american_profit(price: float) -> float:
    p = float(price)
    if p == 0:
        die("NFL_V2G_PAPER_ZERO_AMERICAN_PRICE")
    return 100.0 / (-p) if p < 0 else p / 100.0


def devig_two_way(price_a: float, price_b: float) -> tuple[float, float]:
    a, b = american_implied(price_a), american_implied(price_b)
    denom = a + b
    if denom <= 0:
        die("NFL_V2G_PAPER_DEVIG_INVALID")
    return a / denom, b / denom


def validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA:
        die("NFL_V2G_PAPER_POLICY_SCHEMA_INVALID")
    if policy.get("status") != "FROZEN_BEFORE_FIRST_WEEK2_OPENER_CAPTURE":
        die("NFL_V2G_PAPER_POLICY_STATUS_INVALID")
    selection = policy.get("paper_selection") or {}
    if selection.get("source_window") != "OPENER_ONLY":
        die("NFL_V2G_PAPER_POLICY_WINDOW_INVALID")
    if selection.get("book") != "draftkings":
        die("NFL_V2G_PAPER_POLICY_BOOK_INVALID")
    if set(selection.get("markets") or []) != {"spreads", "totals"}:
        die("NFL_V2G_PAPER_POLICY_MARKETS_INVALID")
    if selection.get("positive_after_vig_ev_required") is not True:
        die("NFL_V2G_PAPER_POLICY_POSITIVE_EV_REQUIRED")
    if selection.get("backfill_allowed") is not False or selection.get("staking_allowed") is not False:
        die("NFL_V2G_PAPER_POLICY_GOVERNANCE_INVALID")


def validate_prediction(pred: dict[str, Any], policy: dict[str, Any]) -> None:
    if pred.get("schema_version") != PRED_SCHEMA:
        die("NFL_V2G_PAPER_PREDICTION_SCHEMA_INVALID")
    if pred.get("candidate_id") != policy.get("candidate_id"):
        die("NFL_V2G_PAPER_CANDIDATE_ID_MISMATCH")
    if pred.get("artifact_sha256") != policy.get("frozen_research_artifact_sha256"):
        die("NFL_V2G_PAPER_ARTIFACT_MISMATCH")
    if pred.get("market_prices_consumed") is not False:
        die("NFL_V2G_PAPER_PREDICTION_MARKET_LEAKAGE")
    for key in ("promotion_authority", "may_create_model_p", "market_eligibility_changed", "official_status_granted"):
        if pred.get(key) is not False:
            die(f"NFL_V2G_PAPER_PREDICTION_AUTHORITY_INVALID:{key}")
    if parse_dt(pred.get("captured_at_utc"), "prediction_captured_at") >= parse_dt(pred.get("kickoff_utc"), "kickoff"):
        die("NFL_V2G_PAPER_PREDICTION_NOT_PREGAME")
    if not isinstance(pred.get("score_distribution"), list) or not pred["score_distribution"]:
        die("NFL_V2G_PAPER_SCORE_DISTRIBUTION_REQUIRED")


def canonical_team(name: str) -> str:
    if name not in TEAM_CODE_BY_NAME:
        die(f"NFL_V2G_PAPER_UNKNOWN_TEAM:{name}")
    return TEAM_CODE_BY_NAME[name]


def validate_opener(opener: dict[str, Any], pred: dict[str, Any], generated: datetime, policy: dict[str, Any]) -> dict[str, Any]:
    if opener.get("capture_kind") != "OPENER":
        die("NFL_V2G_PAPER_OPENER_KIND_INVALID")
    if opener.get("book") != "draftkings" or set(opener.get("markets") or []) != {"spreads", "totals"}:
        die("NFL_V2G_PAPER_OPENER_MARKET_CONTRACT_INVALID")
    if opener.get("lock_status") not in {"MATCH", "LOCK_CREATED"}:
        die(f"NFL_V2G_PAPER_OPENER_LOCK_INVALID:{opener.get('lock_status')}")
    retrieved = parse_dt(opener.get("retrieved_at_utc"), "opener_retrieved_at")
    kickoff = parse_dt(pred.get("kickoff_utc"), "kickoff")
    if retrieved >= kickoff:
        die("NFL_V2G_PAPER_OPENER_NOT_PREGAME")
    if generated < retrieved:
        die("NFL_V2G_PAPER_DECISION_BEFORE_OPENER")
    max_minutes = int((policy.get("paper_selection") or {}).get("max_minutes_after_opener_retrieval", 0))
    if max_minutes <= 0 or generated > retrieved + timedelta(minutes=max_minutes):
        die("NFL_V2G_PAPER_BACKFILL_WINDOW_EXCEEDED")
    if generated >= kickoff:
        die("NFL_V2G_PAPER_DECISION_NOT_PREGAME")
    matches = []
    for row in opener.get("games") or []:
        if canonical_team(str(row.get("away_team") or "")) != pred.get("away_team"):
            continue
        if canonical_team(str(row.get("home_team") or "")) != pred.get("home_team"):
            continue
        commence = parse_dt(row.get("commence_time"), "commence_time")
        if abs((commence - kickoff).total_seconds()) <= 60:
            matches.append(row)
    if len(matches) != 1:
        die(f"NFL_V2G_PAPER_OPENER_MATCH_COUNT:{len(matches)}")
    return matches[0]


def model_spread_probs(distribution: list[dict[str, Any]], home_point: float) -> dict[str, dict[str, float]]:
    home_win = home_loss = push = 0.0
    for row in distribution:
        w = float(row["weight"])
        value = float(row["margin"]) + float(home_point)
        if value > 0:
            home_win += w
        elif value < 0:
            home_loss += w
        else:
            push += w
    denom = home_win + home_loss
    if denom <= 0:
        die("NFL_V2G_PAPER_SPREAD_NONPUSH_MASS_ZERO")
    return {
        "home": {"win": home_win, "loss": home_loss, "push": push, "conditional": home_win / denom},
        "away": {"win": home_loss, "loss": home_win, "push": push, "conditional": home_loss / denom},
    }


def model_total_probs(distribution: list[dict[str, Any]], point: float) -> dict[str, dict[str, float]]:
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
        die("NFL_V2G_PAPER_TOTAL_NONPUSH_MASS_ZERO")
    return {
        "over": {"win": over, "loss": under, "push": push, "conditional": over / denom},
        "under": {"win": under, "loss": over, "push": push, "conditional": under / denom},
    }


def decide_market(market: str, row: dict[str, Any], pred: dict[str, Any], edge_floor: float) -> dict[str, Any]:
    if market == "spread":
        offered = row.get("spread") or {}
        if offered.get("status") != "OK":
            return {"status": "NO_PAPER_DECISION_MARKET_UNAVAILABLE", "market": market}
        hp, ap = float(offered["home_point"]), float(offered["away_point"])
        if abs(hp + ap) > 1e-9:
            die("NFL_V2G_PAPER_SPREAD_LINE_MISMATCH")
        hprice, aprice = float(offered["home_price"]), float(offered["away_price"])
        hmkt, amkt = devig_two_way(hprice, aprice)
        model = model_spread_probs(pred["score_distribution"], hp)
        sides = [
            ("home", pred["home_team"], hp, hprice, hmkt, model["home"]),
            ("away", pred["away_team"], ap, aprice, amkt, model["away"]),
        ]
    elif market == "total":
        offered = row.get("total") or {}
        if offered.get("status") != "OK":
            return {"status": "NO_PAPER_DECISION_MARKET_UNAVAILABLE", "market": market}
        point = float(offered["point"])
        oprice, uprice = float(offered["over_price"]), float(offered["under_price"])
        omkt, umkt = devig_two_way(oprice, uprice)
        model = model_total_probs(pred["score_distribution"], point)
        sides = [
            ("over", "OVER", point, oprice, omkt, model["over"]),
            ("under", "UNDER", point, uprice, umkt, model["under"]),
        ]
    else:
        die(f"NFL_V2G_PAPER_UNKNOWN_MARKET:{market}")

    ranked = []
    for side, selection, line, price, market_p, probs in sides:
        edge = float(probs["conditional"]) - float(market_p)
        ev = float(probs["win"]) * american_profit(price) - float(probs["loss"])
        ranked.append({
            "side": side,
            "selection": selection,
            "line": line,
            "price": price,
            "market_no_vig_probability": market_p,
            "model_probability_conditional_no_push": float(probs["conditional"]),
            "model_win_probability": float(probs["win"]),
            "model_loss_probability": float(probs["loss"]),
            "model_push_probability": float(probs["push"]),
            "edge_probability": edge,
            "expected_value_units_per_unit": ev,
        })
    ranked.sort(key=lambda x: x["edge_probability"], reverse=True)
    top = ranked[0]
    tied = abs(ranked[0]["edge_probability"] - ranked[1]["edge_probability"]) <= 1e-12
    if tied or top["edge_probability"] < edge_floor or top["expected_value_units_per_unit"] <= 0:
        return {
            "status": "NO_PAPER_EDGE_OR_PRICE",
            "market": market,
            "edge_floor_probability": edge_floor,
            "positive_after_vig_ev_required": True,
            "candidates": ranked,
        }
    return {
        "status": "PAPER_CANDIDATE",
        "market": market,
        "edge_floor_probability": edge_floor,
        "positive_after_vig_ev_required": True,
        "selection": top,
        "candidates": ranked,
    }


def build(pred_path: Path, opener_path: Path, policy_path: Path, generated_at_utc: str) -> dict[str, Any]:
    pred, pred_file_sha = load_json(pred_path)
    opener, opener_file_sha = load_json(opener_path)
    policy, policy_file_sha = load_json(policy_path)
    validate_policy(policy)
    validate_prediction(pred, policy)
    generated = parse_dt(generated_at_utc, "generated_at_utc")
    opener_row = validate_opener(opener, pred, generated, policy)
    edge_floor = float(policy["paper_selection"]["edge_floor_probability"])
    decisions = {
        "spread": decide_market("spread", opener_row, pred, edge_floor),
        "total": decide_market("total", opener_row, pred, edge_floor),
    }
    paper_count = sum(d.get("status") == "PAPER_CANDIDATE" for d in decisions.values())
    output: dict[str, Any] = {
        "schema_version": OUT_SCHEMA,
        "status": "PAPER_CANDIDATES_FROZEN" if paper_count else "NO_PAPER_EDGE",
        "game_id": pred["game_id"],
        "candidate_id": pred["candidate_id"],
        "artifact_sha256": pred["artifact_sha256"],
        "prediction_sha256": pred.get("prediction_sha256"),
        "prediction_file_sha256": pred_file_sha,
        "opener_capture_file_sha256": opener_file_sha,
        "policy_file_sha256": policy_file_sha,
        "policy_schema_version": policy["schema_version"],
        "away_team": pred["away_team"],
        "home_team": pred["home_team"],
        "kickoff_utc": pred["kickoff_utc"],
        "prediction_captured_at_utc": pred["captured_at_utc"],
        "opener_retrieved_at_utc": opener["retrieved_at_utc"],
        "decision_generated_at_utc": generated.isoformat(),
        "book": "draftkings",
        "decisions": decisions,
        "paper_candidate_count": paper_count,
        "market_prices_consumed_by_model": False,
        "paper_research_only": True,
        "staking_allowed": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "market_eligibility_changed": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }
    output["paper_decision_sha256"] = sha256_bytes(canonical_bytes({k: v for k, v in output.items() if k != "paper_decision_sha256"}))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--opener", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.prediction, args.opener, args.policy, args.generated_at_utc)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and args.output.read_text(encoding="utf-8") != encoded:
        die(f"NFL_V2G_PAPER_REFUSING_OVERWRITE:{args.output}")
    args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({"game_id": result["game_id"], "status": result["status"], "paper_candidate_count": result["paper_candidate_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
