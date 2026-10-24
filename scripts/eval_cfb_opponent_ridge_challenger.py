#!/usr/bin/env python3
"""Chronological CFB ridge challenger vs non-certified line references only."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.cfb_opponent_ridge_challenger import (
    fit, predict, reference_probabilities, utc, SCHEMA,
)

def evaluate(rows, *, season=2025, min_team_games=3):
    """Walk forward: no target result enters its own pregame model fit."""
    if not isinstance(rows, list) or type(season) is not int:
        raise ValueError("CFB_EVALUATION_INPUT_INVALID")
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CFB_ROW_INVALID")
        game = str(row.get("game_id") or "")
        if not game or game in ids:
            raise ValueError("CFB_GAME_ID_DUPLICATE")
        ids.add(game)
    targets = sorted((x for x in rows if x.get("season") == season),
                     key=lambda x: (utc(x["kickoff_utc"]), str(x["game_id"])))
    evaluated = []
    brier_spread = brier_total = 0.0
    spread_count = total_count = 0
    spread_pushes = total_pushes = missing_history = 0
    model_margin_mae = ref_margin_mae = 0.0
    model_total_mae = ref_total_mae = 0.0
    ref_count = 0
    for target in targets:
        kickoff = utc(target["kickoff_utc"])
        try:
            trained = fit(rows, as_of=kickoff, season=season)
        except ValueError as exc:
            if str(exc) != "CFB_NO_PREGAME_FINALS":
                raise
            missing_history += 1
            continue
        output = predict(trained, home=target["home"], away=target["away"],
                         neutral_site=target["neutral_site"])
        if min(output["home_games"], output["away_games"]) < min_team_games:
            missing_history += 1
            continue
        if utc(trained["last_result_observed_at_utc"]) >= kickoff:
            raise ValueError("CFB_CHRONO_LOOKAHEAD")
        actual_margin = target["home_points"] - target["away_points"]
        actual_total = target["home_points"] + target["away_points"]
        record = {"game_id": target["game_id"], "kickoff_utc": kickoff.isoformat(),
                  "last_used_result_utc": trained["last_result_observed_at_utc"],
                  "trained_games": trained["trained_games"],
                  "predicted_margin": output["margin_home"],
                  "predicted_total": output["total"],
                  "play_authority": False}
        spread, total_line = target.get("reference_spread_home"), target.get("reference_total")
        if spread is not None and total_line is not None:
            p = reference_probabilities(output, home_spread=spread, total_line=total_line)
            ref_count += 1
            model_margin_mae += abs(output["margin_home"] - actual_margin)
            ref_margin_mae += abs(-spread - actual_margin)
            model_total_mae += abs(output["total"] - actual_total)
            ref_total_mae += abs(total_line - actual_total)
            spread_result = actual_margin + spread
            total_result = actual_total - total_line
            sp = p["spread_home"]
            to = p["total_over"]
            if spread_result == 0:
                spread_pushes += 1
            else:
                cover_p = sp["above"] / (1 - sp["push"])
                brier_spread += (cover_p - (1 if spread_result > 0 else 0)) ** 2
                spread_count += 1
            if total_result == 0:
                total_pushes += 1
            else:
                over_p = to["above"] / (1 - to["push"])
                brier_total += (over_p - (1 if total_result > 0 else 0)) ** 2
                total_count += 1
        else:
            record["reason"] = "HISTORICAL_REFERENCE_MISSING"
        evaluated.append(record)
    def mean(value, count):
        return round(value / count, 5) if count else None
    return {"schema": SCHEMA, "status": "SCREEN_NOT_VALIDATED",
            "season": season, "targets": len(targets),
            "eligible": len(evaluated), "insufficient_history": missing_history,
            "reference_rows": ref_count,
            "spread_brier": mean(brier_spread, spread_count),
            "total_brier": mean(brier_total, total_count),
            "spread_nonpush": spread_count, "total_nonpush": total_count,
            "spread_pushes": spread_pushes, "total_pushes": total_pushes,
            "model_margin_mae": mean(model_margin_mae, ref_count),
            "reference_margin_mae": mean(ref_margin_mae, ref_count),
            "model_total_mae": mean(model_total_mae, ref_count),
            "reference_total_mae": mean(ref_total_mae, ref_count),
            "market_references": "RESEARCH_ONLY_NOT_CERTIFIED_EXECUTABLE_CLOSE",
            "model_p_approved": False, "play_authority": False,
            "promotion_authority": False, "predictions": evaluated}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=Path, required=True)
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = evaluate(json.loads(args.games.read_text(encoding="utf-8")), season=args.season)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "status", "eligible", "spread_brier", "total_brier",
        "model_margin_mae", "reference_margin_mae", "play_authority")}, sort_keys=True))

if __name__ == "__main__":
    main()
