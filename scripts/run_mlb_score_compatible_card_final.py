#!/usr/bin/env python3
"""Run one score-compatible MLB game and emit a fail-closed same-game card.

This wrapper narrows the canonical manual snapshot to one game, delegates all
probability generation to ``run_mlb_score_compatible_joint_research``, and then
applies presentation-only consistency rules. It never changes a probability.

Governance: research-only, NOT Model_P, NOT Truth Gate, NOT OFFICIAL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from scripts.run_mlb_score_compatible_joint_research import run as run_joint

MAX_STRAIGHT_JUICE = -165
GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})
PITCHER_MARKETS = frozenset({
    "PITCHER_K",
    "PITCHER_OUTS",
    "PITCHER_ER",
    "PITCHER_HITS_ALLOWED",
    "PITCHER_BB",
    "PITCHER_HITS_WALKS_ER",
})


def _build_consistency_card(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Surface at most one correlated game play; pitcher props fail closed.

    The merged score-compatible coupling removes impossible score/pitcher states,
    but its own research contract says the remaining dependence is not calibrated.
    Pitcher rows therefore remain research diagnostics rather than card plays.
    """
    candidates = [
        row for row in results
        if str(row.get("engine_market") or "").upper() in GAME_MARKETS
        and float(row.get("ev_per_dollar") or 0.0) > 0.0
        and int(row.get("american_odds") or -10000) >= MAX_STRAIGHT_JUICE
    ]
    primary = max(candidates, key=lambda row: float(row["ev_per_dollar"]), default=None)

    decisions: list[dict[str, Any]] = []
    for row in results:
        market = str(row.get("engine_market") or "").upper()
        decision = {
            "market_type": row.get("market_type"),
            "engine_market": market,
            "side": row.get("side"),
            "line": row.get("line"),
            "american_odds": row.get("american_odds"),
            "team_side": row.get("team_side"),
            "pitcher_name": row.get("pitcher_name"),
            "research_p": row.get("research_p"),
            "push_p": row.get("push_p"),
            "settled_research_p": row.get("settled_research_p"),
            "raw_edge_points": row.get("raw_edge_points"),
            "ev_per_dollar": row.get("ev_per_dollar"),
            "simulation_id": row.get("simulation_id"),
        }
        if market in PITCHER_MARKETS:
            decision.update({
                "card_status": "PASS",
                "card_reason": "PITCHER_DEPENDENCE_NOT_TEMPORALLY_VALIDATED",
            })
        elif int(row.get("american_odds") or -10000) < MAX_STRAIGHT_JUICE:
            decision.update({"card_status": "PASS", "card_reason": "STRAIGHT_JUICE_CAP"})
        elif float(row.get("ev_per_dollar") or 0.0) <= 0.0:
            decision.update({"card_status": "PASS", "card_reason": "NO_POSITIVE_RESEARCH_EV"})
        elif primary is row:
            decision.update({
                "card_status": "PRIMARY_RESEARCH_PLAY",
                "card_reason": "HIGHEST_POSITIVE_EV_COHERENT_GAME_ROW",
            })
        else:
            decision.update({"card_status": "PASS", "card_reason": "SAME_GAME_CORRELATION_GUARD"})
        decisions.append(decision)

    return {
        "policy": "ONE_COHERENT_GAME_PLAY_PITCHER_PROPS_FAIL_CLOSED",
        "max_straight_juice": MAX_STRAIGHT_JUICE,
        "pitcher_props_eligible": False,
        "pitcher_props_reason": "PITCHER_DEPENDENCE_NOT_TEMPORALLY_VALIDATED",
        "primary": next((row for row in decisions if row["card_status"] == "PRIMARY_RESEARCH_PLAY"), None),
        "decisions": decisions,
    }


def _filtered_snapshot(input_path: Path, game_id: str) -> tuple[dict[str, Any], Path]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("input must be a JSON object")
    rows = raw.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("input must contain non-empty rows")
    selected = [row for row in rows if str(row.get("game_id") or "") == game_id]
    if not selected:
        raise ValueError(f"game_id not found in input: {game_id}")
    payload = dict(raw)
    payload["rows"] = selected
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        temp_path = Path(handle.name)
    return payload, temp_path


def run(input_path: Path, *, game_id: str, simulations: int = 100000) -> dict[str, Any]:
    selected, temp_path = _filtered_snapshot(input_path, game_id)
    try:
        payload = run_joint(temp_path, simulations=simulations)
    finally:
        temp_path.unlink(missing_ok=True)

    payload["input_path"] = str(input_path)
    payload["selected_game_id"] = game_id
    payload["selected_row_count"] = len(selected["rows"])
    payload["card"] = _build_consistency_card(payload["results"])
    payload["display_policy"] = {
        "probability_source": "score-compatible joint research path set",
        "probabilities_modified_by_card_guard": False,
        "same_game_primary_limit": 1,
        "pitcher_props": "PASS_UNTIL_TEMPORAL_DEPENDENCE_VALIDATION",
        "unsourced_bio_or_advanced_driver_claims": "OMIT",
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--simulations", type=int, default=100000)
    args = parser.parse_args()

    payload = run(Path(args.input), game_id=str(args.game_id), simulations=int(args.simulations))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"wrote {out}: games={len(payload['games'])} results={len(payload['results'])}")
    for game in payload["games"]:
        script = game["game_script"]
        print(
            f"GAME {game['away_team']} @ {game['home_team']} "
            f"sim={game['simulation_id'][:12]} paths={game['mc_paths']} "
            f"mean={script['away_mean_runs']:.3f}-{script['home_mean_runs']:.3f} "
            f"total={script['total_mean_runs']:.3f} "
            f"<=5={script['runs_le_5_p']:.3%} =6={script['runs_eq_6_p']:.3%} >=7={script['runs_ge_7_p']:.3%}"
        )
        compat = game.get("pitcher_score_compatibility") or {}
        print(f"PITCHER_SCORE_COMPAT {json.dumps(compat, sort_keys=True)}")

    for row in payload["results"]:
        print(
            f"ROW {row['market_type']} {row.get('pitcher_name') or row.get('team_side') or 'GAME'} "
            f"{row['side']} {row['line']:g} {row['american_odds']:+d} "
            f"p={row['research_p']:.3%} push={row['push_p']:.3%} "
            f"settled={row['settled_research_p']:.3%} edge={row['raw_edge_points']:+.2f}pt ev={row['ev_per_dollar']:+.4f}"
        )

    primary = payload["card"]["primary"]
    if primary:
        print(
            f"CARD PRIMARY {primary['market_type']} {primary.get('team_side') or 'GAME'} "
            f"{primary['side']} {primary['line']:g} {primary['american_odds']:+d} "
            f"p={primary['settled_research_p']:.3%} ev={primary['ev_per_dollar']:+.4f}"
        )
    else:
        print("CARD NO_PRIMARY_PLAY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
