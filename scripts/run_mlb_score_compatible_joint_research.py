#!/usr/bin/env python3
"""Run research game paths with canonical standalone pitcher marginals.

The script starts from a canonical manual-input snapshot. Context-adjusted game
run means are produced by the existing research lane, pitcher pools are built from
strictly-prior StatsAPI starts, and supported full-game + pitcher markets are then
priced with explicit per-row engine provenance. Score-conditioned pitcher values
are diagnostics only; they are not used for standalone pitcher EV.

Nothing here emits Model_P or grants Truth Gate/official status.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from scripts.run_mlb_context_adjusted_research import economics, run as run_context_adjusted
from sportsedge.canonical_manual_mlb import _resolve_game, _resolve_subject
from sportsedge.manual_quote import validate_manual_quote
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_joint_card_coupled_research import simulate_score_compatible_joint_card
from sportsedge.mlb_joint_features import build_pitcher_joint_features
from sportsedge.pitcher_joint_engine import price_pitcher_market
from sportsedge.source_lineage import canonical_json_sha256

MARKET_MAP = {
    "MONEYLINE": "MONEYLINE",
    "RUN_LINE": "RUN_LINE",
    "GAME_TOTAL": "TOTALS",
    "TEAM_TOTALS": "TEAM_TOTALS",
    "TEAM_TOTAL": "TEAM_TOTALS",
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
PITCHER_MARKETS = frozenset({
    "PITCHER_K",
    "PITCHER_OUTS",
    "PITCHER_ER",
    "PITCHER_HITS_ALLOWED",
    "PITCHER_BB",
    "PITCHER_HITS_WALKS_ER",
})


def _paired(row) -> list[tuple[str, int, float]]:
    paired_line = -float(row.line) if row.market_type == "RUN_LINE" else float(row.line)
    return [
        (str(row.side).upper(), int(row.price), float(row.line)),
        (str(row.paired_side).upper(), int(row.paired_price), paired_line),
    ]


def _selection_id(*, row_index: int, side_index: int, market: str, entity_id: str) -> str:
    return f"{row_index}:{side_index}:{market}:{entity_id}"


def run(input_path: Path, *, simulations: int = 100000) -> dict[str, Any]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    rows_raw = raw.get("rows") if isinstance(raw, Mapping) else None
    if not isinstance(rows_raw, list) or not rows_raw:
        raise ValueError("input must contain non-empty rows")
    parsed = [validate_manual_quote(row) for row in rows_raw]

    # This lane deliberately reuses the already-audited context-adjusted game
    # baseline. It does not reconstruct a second game model.
    context_payload = run_context_adjusted(input_path)
    context_by_game = {str(game["game_id"]): game for game in context_payload["games"]}

    by_game: dict[str, list[tuple[int, Any]]] = {}
    for index, row in enumerate(parsed):
        if str(row.market_type).upper() in MARKET_MAP:
            by_game.setdefault(str(row.game_id), []).append((index, row))

    games_out: list[dict[str, Any]] = []
    results_out: list[dict[str, Any]] = []

    for game_key, indexed_rows in by_game.items():
        context_game = context_by_game.get(game_key)
        if not isinstance(context_game, Mapping):
            raise ValueError(f"missing context-adjusted game metadata for {game_key}")
        adjusted = context_game.get("adjusted_means") or {}
        if not isinstance(adjusted, Mapping):
            raise ValueError(f"missing adjusted means for {game_key}")
        context_feature_hash = str(context_game.get("feature_source_hash") or "")
        if not context_feature_hash:
            raise ValueError(f"missing context feature hash for {game_key}")

        anchor = max((row for _, row in indexed_rows), key=lambda row: row.observed_at)
        resolved = _resolve_game(anchor)
        target_date = datetime.fromisoformat(str(resolved.official_date)).date()
        retrieved_at = datetime.fromisoformat(str(context_game["context_as_of_utc"]))
        history = MLBAllMarketHistorySource(retrieved_at=retrieved_at)

        pitcher_pools: dict[str, list[dict[str, int]]] = {}
        pitcher_feature_hashes: dict[str, str] = {}
        pitcher_team_sides: dict[str, str] = {}
        pitcher_names: dict[str, str] = {}
        pitcher_inputs: dict[tuple[str, str], dict[str, Any]] = {}
        selections: list[dict[str, Any]] = []
        presentation: dict[str, dict[str, Any]] = {}

        for row_index, row in indexed_rows:
            market = MARKET_MAP[str(row.market_type).upper()]
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
                    raise ValueError("TEAM_TOTALS requires team_side")
            elif market in PITCHER_MARKETS:
                subject_id, subject_team_id = _resolve_subject(row, game=resolved)
                if not subject_id:
                    raise ValueError(f"could not resolve pitcher {row.subject_name or row.subject_id}")
                if subject_team_id == resolved.away_id:
                    pitcher_side = "AWAY"
                elif subject_team_id == resolved.home_id:
                    pitcher_side = "HOME"
                else:
                    raise ValueError(f"pitcher not in resolved game: {row.subject_name or subject_id}")
                pitcher_id = str(subject_id)
                entity_id = pitcher_id
                pitcher_names[pitcher_id] = str(row.subject_name or subject_id)
                if pitcher_id in pitcher_team_sides and pitcher_team_sides[pitcher_id] != pitcher_side:
                    raise ValueError(f"pitcher side changed inside game: {pitcher_id}")
                pitcher_team_sides[pitcher_id] = pitcher_side
                if pitcher_id not in pitcher_pools:
                    features = build_pitcher_joint_features(
                        history,
                        pitcher_id=int(pitcher_id),
                        target_date=target_date,
                    )
                    pitcher_pools[pitcher_id] = [dict(item) for item in features["history_pool"]]
                    pitcher_feature_hashes[pitcher_id] = str(features["feature_source_hash"])
                input_key = (pitcher_id, market)
                if input_key not in pitcher_inputs:
                    pitcher_inputs[input_key] = history.feature_row(
                        game_pk=int(resolved.game_pk), market=market, entity_id=pitcher_id,
                        target_date=target_date, away_team_id=int(resolved.away_id),
                        home_team_id=int(resolved.home_id), player_id=int(pitcher_id),
                        team_id=int(subject_team_id),
                    )

            for side_index, (side, price, line) in enumerate(_paired(row)):
                sid = _selection_id(
                    row_index=row_index,
                    side_index=side_index,
                    market=market,
                    entity_id=entity_id,
                )
                selection: dict[str, Any] = {
                    "selection_id": sid,
                    "market": market,
                    "side": side,
                    "line": line,
                }
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

        joint_feature_hash = canonical_json_sha256({
            "context_feature_hash": context_feature_hash,
            "pitcher_feature_hashes": pitcher_feature_hashes,
            "pitcher_team_sides": pitcher_team_sides,
        })
        joint = simulate_score_compatible_joint_card(
            game_id=str(resolved.game_pk),
            away_mean_runs=float(adjusted["away_mean_runs"]),
            home_mean_runs=float(adjusted["home_mean_runs"]),
            # Pitcher quote membership/history must not reseed game scores.
            feature_source_hash=context_feature_hash,
            selections=selections,
            pitcher_pools=pitcher_pools,
            pitcher_team_sides=pitcher_team_sides,
            simulations=simulations,
        )

        for result in joint["results"]:
            sid = str(result["selection_id"])
            meta = presentation[sid]
            diagnostic = None
            probability_source = "SCORE_COMPATIBLE_GAME_PATHS"
            engine_version = joint["joint_research_version"]
            probability_identity = result["simulation_id"]
            probability_meta = None
            if meta["engine_market"] in PITCHER_MARKETS:
                # Standalone props must not use the ER-conditioned bootstrap:
                # resampling good starts changes K/outs as well as earned runs.
                diagnostic = dict(result)
                built = pitcher_inputs[(meta["pitcher_id"], meta["engine_market"])]
                priced = price_pitcher_market({
                    **built, "game_id": str(resolved.game_pk),
                    "market": meta["engine_market"], "entity_id": meta["pitcher_id"],
                    "side": meta["side"], "line": meta["line"],
                    "feature_source_hash": built.get("feature_source_hash") or built.get("source_subset_hash"),
                })
                result = {
                    **result, "research_p": priced["model_p"], "push_p": priced["push_p"],
                    "loss_p": 1.0 - priced["model_p"] - priced["push_p"],
                    "simulation_id": None, "score_distribution_sha256": None,
                    "mc_paths": priced["mc_paths"],
                }
                probability_source = "CANONICAL_PITCHER_MARGINAL"
                engine_version = priced["engine_version"]
                probability_identity = priced["model_input_hash"]
                probability_meta = priced["meta"]
            econ = economics(
                win_p=float(result["research_p"]),
                push_p=float(result["push_p"]),
                odds=int(meta["american_odds"]),
            )
            results_out.append({
                **meta,
                "research_p": float(result["research_p"]),
                "push_p": float(result["push_p"]),
                "loss_p": float(result["loss_p"]),
                "pitcher_conditioning_audit": result.get("pitcher_conditioning_audit"),
                "score_conditioned_diagnostic": diagnostic,
                "probability_source": probability_source,
                "probability_identity": probability_identity,
                "engine_version": engine_version,
                "probability_meta": probability_meta,
                "same_game_joint_eligible": False,
                "postseason_workload_adjusted": False if diagnostic is not None else None,
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
            "pitcher_team_sides": pitcher_team_sides,
            "pitcher_names": pitcher_names,
            "simulation_id": joint["simulation_id"],
            "score_distribution_sha256": joint["score_distribution_sha256"],
            "mc_paths": joint["mc_paths"],
            "pitcher_coupling": joint["pitcher_coupling"],
            "pitcher_score_compatibility": joint["pitcher_score_compatibility"],
            "game_script": joint["game_script"],
            "consistency": joint["consistency"],
            "limitations": joint["limitations"],
            "provenance": context_game.get("provenance"),
        })

    results_out.sort(key=lambda row: (
        row["game_pk"], row["market_type"], str(row.get("entity_id")), row["side"], row["line"]
    ))
    return {
        "schema_version": 3,
        "run_type": "MLB_GAME_PATHS_AND_CANONICAL_PITCHER_MARGINALS_RESEARCH",
        "label": "NOT_MODEL_P",
        "truth_gate": False,
        "official": False,
        "promotion_evidence": False,
        "input_path": str(input_path),
        "input_sha256": canonical_json_sha256(raw),
        "games": games_out,
        "results": results_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--simulations", type=int, default=100000)
    args = parser.parse_args()
    payload = run(Path(args.input), simulations=args.simulations)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}: games={len(payload['games'])} results={len(payload['results'])}")
    for game in payload["games"]:
        script = game["game_script"]
        print(
            f"{game['away_team']} @ {game['home_team']}: "
            f"sim={game['simulation_id'][:12]} paths={game['mc_paths']} "
            f"mean={script['away_mean_runs']:.3f}-{script['home_mean_runs']:.3f} "
            f"total={script['total_mean_runs']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
