#!/usr/bin/env python3
"""Run one coherent research path set for MLB game lines and pitcher props.

Game ML/RL/totals/team totals are settled from one V7 score path set. Supported
pitcher props use player-specific whole-start bootstraps indexed to those paths,
so duplicate generic pitcher probabilities are impossible. Pitcher outcomes are
not yet statistically conditioned on the simulated final score; therefore pitcher
props fail closed on the public card and the output remains NOT Model_P / NOT
Truth Gate / NOT OFFICIAL.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from scripts.run_mlb_context_adjusted_research import economics, run as run_context_adjusted
from sportsedge.canonical_manual_mlb import _resolve_game, _resolve_subject
from sportsedge.manual_quote import validate_manual_quote
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_joint_card_research import GAME_MARKETS, PITCHER_MARKETS, simulate_joint_card
from sportsedge.mlb_joint_features import build_pitcher_joint_features
from sportsedge.source_lineage import canonical_json_sha256

MARKET_MAP = {
    "MONEYLINE": "MONEYLINE",
    "RUN_LINE": "RUN_LINE",
    "GAME_TOTAL": "TOTALS",
    "TEAM_TOTALS": "TEAM_TOTALS",
    "PITCHER_STRIKEOUTS": "PITCHER_K",
    "PITCHER_K": "PITCHER_K",
    "PITCHER_OUTS": "PITCHER_OUTS",
    "PITCHER_EARNED_RUNS": "PITCHER_ER",
    "PITCHER_ER": "PITCHER_ER",
    "PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
    "PITCHER_WALKS": "PITCHER_BB",
    "PITCHER_BB": "PITCHER_BB",
    "PITCHER_HITS_WALKS_ER": "PITCHER_HITS_WALKS_ER",
}
MAX_STRAIGHT_JUICE = -165


def _paired(row) -> list[tuple[str, int, float]]:
    paired_line = -float(row.line) if row.market_type == "RUN_LINE" else float(row.line)
    return [
        (str(row.side).upper(), int(row.price), float(row.line)),
        (str(row.paired_side).upper(), int(row.paired_price), paired_line),
    ]


def _selection_id(*, row_index: int, side_index: int, market: str, entity_id: str) -> str:
    return f"{row_index}:{side_index}:{market}:{entity_id}"


def _context_payload(input_path: Path, rows_raw: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Run context-adjusted means on exactly the rows selected for this run."""
    original = json.loads(input_path.read_text(encoding="utf-8"))
    selected = dict(original) if isinstance(original, Mapping) else {}
    selected["rows"] = rows_raw
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(selected, handle, sort_keys=True)
        temp_path = Path(handle.name)
    try:
        return run_context_adjusted(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _build_consistency_card(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail closed until score-conditioned pitcher coupling is validated.

    All pitcher rows are research-only. Among the strongly correlated full-game
    score markets, surface at most one straight play: the positive-EV row with the
    largest simulated expected return that is within the straight-bet juice cap.
    This prevents ML/RL/team-total stacking and prevents a pitcher prop from
    telling the opposite story from the game side.
    """
    game_candidates = [
        row for row in results
        if row["engine_market"] in GAME_MARKETS
        and float(row["ev_per_dollar"]) > 0.0
        and int(row["american_odds"]) >= MAX_STRAIGHT_JUICE
    ]
    primary = max(game_candidates, key=lambda row: float(row["ev_per_dollar"]), default=None)
    decisions: list[dict[str, Any]] = []
    for row in results:
        key = {
            "market_type": row["market_type"],
            "engine_market": row["engine_market"],
            "side": row["side"],
            "line": row["line"],
            "american_odds": row["american_odds"],
            "pitcher_name": row.get("pitcher_name"),
            "team_side": row.get("team_side"),
            "research_p": row["research_p"],
            "push_p": row["push_p"],
            "settled_research_p": row["settled_research_p"],
            "raw_edge_points": row["raw_edge_points"],
            "ev_per_dollar": row["ev_per_dollar"],
        }
        if row["engine_market"] in PITCHER_MARKETS:
            key.update({"card_status": "PASS", "card_reason": "PITCHER_SCORE_DEPENDENCE_NOT_VALIDATED"})
        elif int(row["american_odds"]) < MAX_STRAIGHT_JUICE:
            key.update({"card_status": "PASS", "card_reason": "STRAIGHT_JUICE_CAP"})
        elif float(row["ev_per_dollar"]) <= 0.0:
            key.update({"card_status": "PASS", "card_reason": "NO_POSITIVE_RESEARCH_EV"})
        elif primary is not None and row is primary:
            key.update({"card_status": "PRIMARY_RESEARCH_PLAY", "card_reason": "HIGHEST_POSITIVE_EV_COHERENT_GAME_ROW"})
        else:
            key.update({"card_status": "PASS", "card_reason": "SAME_GAME_CORRELATION_GUARD"})
        decisions.append(key)
    return {
        "policy": "ONE_COHERENT_GAME_PLAY_PITCHER_PROPS_FAIL_CLOSED",
        "max_straight_juice": MAX_STRAIGHT_JUICE,
        "pitcher_props_eligible": False,
        "pitcher_props_reason": "PITCHER_SCORE_DEPENDENCE_NOT_VALIDATED",
        "primary": next((row for row in decisions if row["card_status"] == "PRIMARY_RESEARCH_PLAY"), None),
        "decisions": decisions,
    }


def run(input_path: Path, *, game_id: str | None = None, simulations: int = 100000) -> dict[str, Any]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    rows_raw = raw.get("rows") if isinstance(raw, Mapping) else None
    if not isinstance(rows_raw, list) or not rows_raw:
        raise ValueError("input must contain non-empty rows")
    if game_id:
        rows_raw = [row for row in rows_raw if str(row.get("game_id") or "") == str(game_id)]
        if not rows_raw:
            raise ValueError(f"game_id not found in input: {game_id}")

    parsed = [validate_manual_quote(row) for row in rows_raw]
    context_payload = _context_payload(input_path, rows_raw)
    context_by_game = {str(game["game_id"]): game for game in context_payload["games"]}

    by_game: dict[str, list[tuple[int, Any]]] = {}
    for i, row in enumerate(parsed):
        by_game.setdefault(str(row.game_id), []).append((i, row))

    games_out: list[dict[str, Any]] = []
    results_out: list[dict[str, Any]] = []

    for game_key, indexed_rows in by_game.items():
        context_game = context_by_game.get(game_key)
        if not isinstance(context_game, Mapping):
            raise ValueError(f"missing context-adjusted game metadata for {game_key}")
        adjusted = context_game.get("adjusted_means") or {}
        if not isinstance(adjusted, Mapping):
            raise ValueError(f"missing adjusted means for {game_key}")
        feature_hash = str(context_game.get("feature_source_hash") or "")
        if not feature_hash:
            raise ValueError(f"missing context feature hash for {game_key}")

        anchor = max((row for _, row in indexed_rows), key=lambda row: row.observed_at)
        resolved = _resolve_game(anchor)
        target_date = datetime.fromisoformat(str(resolved.official_date)).date()
        retrieved_at = datetime.fromisoformat(str(context_game["context_as_of_utc"]))
        history = MLBAllMarketHistorySource(retrieved_at=retrieved_at)

        pitcher_pools: dict[str, list[dict[str, int]]] = {}
        pitcher_feature_hashes: dict[str, str] = {}
        pitcher_names: dict[str, str] = {}
        selections: list[dict[str, Any]] = []
        presentation: dict[str, dict[str, Any]] = {}

        for row_index, row in indexed_rows:
            market = MARKET_MAP.get(str(row.market_type).upper())
            if market is None or market not in GAME_MARKETS | PITCHER_MARKETS:
                continue

            pitcher_id: str | None = None
            entity_id = str(resolved.game_pk)
            team_side = None
            if market == "TEAM_TOTALS":
                team_side = str(row.team_side or "").upper()
                if team_side == "AWAY":
                    entity_id = str(resolved.away_id)
                elif team_side == "HOME":
                    entity_id = str(resolved.home_id)
                else:
                    raise ValueError("TEAM_TOTALS requires team_side AWAY/HOME")
            elif market in PITCHER_MARKETS:
                subject_id, subject_team_id = _resolve_subject(row)
                if not subject_id:
                    raise ValueError(f"could not resolve pitcher {row.subject_name or row.subject_id}")
                if subject_team_id not in {resolved.away_id, resolved.home_id}:
                    raise ValueError(f"pitcher not in resolved game: {row.subject_name or subject_id}")
                pitcher_id = str(subject_id)
                entity_id = pitcher_id
                pitcher_names[pitcher_id] = str(row.subject_name or subject_id)
                if pitcher_id not in pitcher_pools:
                    features = build_pitcher_joint_features(history, pitcher_id=int(pitcher_id), target_date=target_date)
                    pitcher_pools[pitcher_id] = [dict(item) for item in features["history_pool"]]
                    pitcher_feature_hashes[pitcher_id] = str(features["feature_source_hash"])

            for side_index, (side, price, line) in enumerate(_paired(row)):
                sid = _selection_id(row_index=row_index, side_index=side_index, market=market, entity_id=entity_id)
                selection: dict[str, Any] = {"selection_id": sid, "market": market, "side": side, "line": line}
                if team_side is not None:
                    selection["team_side"] = team_side
                if pitcher_id is not None:
                    selection["pitcher_id"] = pitcher_id
                selections.append(selection)
                presentation[sid] = {
                    "game_id": game_key,
                    "game_pk": int(resolved.game_pk),
                    "market_type": str(row.market_type),
                    "engine_market": market,
                    "entity_id": entity_id,
                    "team_side": team_side,
                    "pitcher_id": pitcher_id,
                    "pitcher_name": pitcher_names.get(pitcher_id) if pitcher_id else None,
                    "side": side,
                    "line": line,
                    "american_odds": price,
                    "book": str(row.book),
                    "observed_at": row.observed_at.isoformat(),
                }

        if not selections:
            raise ValueError(f"no joint-card selections for {game_key}")

        joint_feature_hash = canonical_json_sha256({
            "context_feature_hash": feature_hash,
            "pitcher_feature_hashes": pitcher_feature_hashes,
        })
        joint = simulate_joint_card(
            game_id=str(resolved.game_pk),
            away_mean_runs=float(adjusted["away_mean_runs"]),
            home_mean_runs=float(adjusted["home_mean_runs"]),
            feature_source_hash=joint_feature_hash,
            selections=selections,
            pitcher_pools=pitcher_pools,
            simulations=simulations,
        )

        for result in joint["results"]:
            sid = str(result["selection_id"])
            meta = presentation[sid]
            econ = economics(win_p=float(result["research_p"]), push_p=float(result["push_p"]), odds=int(meta["american_odds"]))
            results_out.append({
                **meta,
                "research_p": float(result["research_p"]),
                "push_p": float(result["push_p"]),
                "loss_p": float(result["loss_p"]),
                **econ,
                "simulation_id": result["simulation_id"],
                "score_distribution_sha256": result["score_distribution_sha256"],
                "mc_paths": result["mc_paths"],
                "label": "NOT_MODEL_P",
                "truth_gate": False,
                "official": False,
                "promotion_evidence": False,
            })

        games_out.append({
            "game_id": game_key,
            "game_pk": int(resolved.game_pk),
            "away_team": str(resolved.away_name),
            "home_team": str(resolved.home_name),
            "context_as_of_utc": context_game["context_as_of_utc"],
            "adjusted_means": adjusted,
            "joint_feature_hash": joint_feature_hash,
            "pitcher_feature_hashes": pitcher_feature_hashes,
            "pitcher_names": pitcher_names,
            "simulation_id": joint["simulation_id"],
            "score_distribution_sha256": joint["score_distribution_sha256"],
            "mc_paths": joint["mc_paths"],
            "pitcher_coupling": joint["pitcher_coupling"],
            "game_script": joint["game_script"],
            "consistency": joint["consistency"],
            "provenance": context_game.get("provenance"),
        })

    results_out.sort(key=lambda row: (row["game_pk"], row["market_type"], str(row.get("entity_id")), row["side"], row["line"]))
    return {
        "schema_version": 1,
        "run_type": "MLB_CONTEXT_ADJUSTED_JOINT_CARD_RESEARCH",
        "label": "NOT_MODEL_P",
        "truth_gate": False,
        "official": False,
        "promotion_evidence": False,
        "input_path": str(input_path),
        "input_sha256": canonical_json_sha256(raw),
        "selected_game_id": game_id,
        "display_policy": {
            "methodology_label": "single score path set plus player-specific pitcher bootstrap",
            "pitcher_bio_stats": "OMIT_UNLESS_RETRIEVED_WITH_PROVENANCE",
            "advanced_driver_claims": "OMIT_UNLESS_RETRIEVED_WITH_PROVENANCE",
            "generic_pitcher_probability_fallback": "FORBIDDEN",
            "pitcher_score_dependence": "NOT_YET_VALIDATED",
        },
        "games": games_out,
        "results": results_out,
        "card": _build_consistency_card(results_out),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--game-id")
    parser.add_argument("--simulations", type=int, default=100000)
    args = parser.parse_args()
    payload = run(Path(args.input), game_id=args.game_id, simulations=args.simulations)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}: games={len(payload['games'])} results={len(payload['results'])}")
    for game in payload["games"]:
        script = game["game_script"]
        print(
            f"GAME {game['away_team']} @ {game['home_team']} sim={game['simulation_id'][:12]} "
            f"paths={game['mc_paths']} mean={script['away_mean_runs']:.3f}-{script['home_mean_runs']:.3f} "
            f"total={script['total_mean_runs']:.3f} <=5={script['runs_le_5_p']:.3%} "
            f"=6={script['runs_eq_6_p']:.3%} >=7={script['runs_ge_7_p']:.3%}"
        )
    for row in payload["results"]:
        print(
            f"ROW {row['market_type']} {row.get('pitcher_name') or row.get('team_side') or 'GAME'} "
            f"{row['side']} {row['line']:g} {row['american_odds']:+d} p={row['research_p']:.3%} "
            f"push={row['push_p']:.3%} settled={row['settled_research_p']:.3%} "
            f"edge={row['raw_edge_points']:+.2f}pt ev={row['ev_per_dollar']:+.4f}"
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
