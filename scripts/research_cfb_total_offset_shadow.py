"""Shadow-price CFB totals after an outcome-trained chronological research offset.

Research ONLY: never modifies a production card, frozen model, betting status,
prices, qualification, limits, or staking. Input calibration is deliberately
research-only and must be separately validated on genuinely new PIT data.
"""
from __future__ import annotations

import argparse
import json
from math import erf, isfinite, sqrt
from pathlib import Path

SCHEMA = "CFB_TOTAL_OFFSET_SHADOW_V1"


def _finite(value, name):
    if isinstance(value, bool):
        raise ValueError("CFB_TOTAL_SHADOW_NUMERIC_INVALID:" + name)
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CFB_TOTAL_SHADOW_NUMERIC_INVALID:" + name) from exc
    if not isfinite(v):
        raise ValueError("CFB_TOTAL_SHADOW_NUMERIC_INVALID:" + name)
    return v


def shadow_adjusted_means(home, away, offset):
    """Add outcome-trained total offset symmetrically, preserving spread mean."""
    h, a, shift = (_finite(home, "home_mean"), _finite(away, "away_mean"),
                   _finite(offset, "offset_points"))
    if abs(shift) > 10:
        raise ValueError("CFB_TOTAL_SHADOW_OFFSET_SUSPECT")
    adjusted_h, adjusted_a = h + shift / 2.0, a + shift / 2.0
    if min(h, a, adjusted_h, adjusted_a) < 0 or max(adjusted_h, adjusted_a) > 75:
        raise ValueError("CFB_TOTAL_SHADOW_TEAM_POINTS_OUTSIDE_BOUNDS")
    return adjusted_h, adjusted_a


def over_probability(model_total, line, sigma):
    sigma = _finite(sigma, "sigma")
    if sigma <= 0:
        raise ValueError("CFB_TOTAL_SHADOW_SIGMA_INVALID")
    value = (_finite(model_total, "total") - _finite(line, "line")) / sigma
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def shadow_card(card, calibration):
    if card.get("schema") != "CFB_SDV_CARD_V2":
        raise ValueError("CFB_TOTAL_SHADOW_CARD_SCHEMA_INVALID")
    if calibration.get("schema") != "CFB_TOTAL_OFFSET_CHRONO_RESEARCH_V1":
        raise ValueError("CFB_TOTAL_SHADOW_CALIBRATION_SCHEMA_INVALID")
    if (calibration.get("calibration_applied_in_production") is not False or
            calibration.get("staking_authority") is not False or
            calibration.get("positive_ev_proven") is not False):
        raise ValueError("CFB_TOTAL_SHADOW_RESEARCH_ONLY_REQUIRED")
    if calibration.get("evidence_class") != "RETROSPECTIVE_RESEARCH_ONLY":
        raise ValueError("CFB_TOTAL_SHADOW_EVIDENCE_CLASS_INVALID")
    offset = _finite(calibration.get("offset_points"), "offset_points")
    if abs(offset) > 10:
        raise ValueError("CFB_TOTAL_SHADOW_OFFSET_SUSPECT")
    sigma = _finite(card.get("combined_sigma"), "combined_sigma")
    if sigma <= 0:
        raise ValueError("CFB_TOTAL_SHADOW_SIGMA_INVALID")
    rows = card.get("results")
    if not isinstance(rows, list):
        raise ValueError("CFB_TOTAL_SHADOW_RESULTS_REQUIRED")
    grouped = {}
    for row in rows:
        if row.get("market") != "TOTAL" or row.get("devig") != "PAIRED_PROPORTIONAL":
            continue
        gid = str(row.get("game_id") or "")
        if not gid:
            raise ValueError("CFB_TOTAL_SHADOW_GAME_ID_REQUIRED")
        grouped.setdefault(gid, []).append(row)
    shadows = []
    for game_id, entries in sorted(grouped.items()):
        if len(entries) != 2 or {r.get("side") for r in entries} != {"OVER", "UNDER"}:
            raise ValueError("CFB_TOTAL_SHADOW_UNIQUE_OPPOSITES_REQUIRED:" + game_id)
        over = next(r for r in entries if r["side"] == "OVER")
        under = next(r for r in entries if r["side"] == "UNDER")
        line = _finite(over.get("line"), "line")
        if line != _finite(under.get("line"), "opposite_line"):
            raise ValueError("CFB_TOTAL_SHADOW_LINE_MISMATCH:" + game_id)
        home = _finite(over.get("home_mean"), "home_mean")
        away = _finite(over.get("away_mean"), "away_mean")
        if (abs(home - _finite(under.get("home_mean"), "opposite_home_mean")) > 0.02 or
                abs(away - _finite(under.get("away_mean"), "opposite_away_mean")) > 0.02):
            raise ValueError("CFB_TOTAL_SHADOW_SCORE_MISMATCH:" + game_id)
        adj_home, adj_away = shadow_adjusted_means(home, away, offset)
        shadows.append({
            "game_id": game_id, "matchup": over.get("matchup"),
            "market_total": line,
            "original_model_total": round(home + away, 4),
            "shadow_model_total": round(adj_home + adj_away, 4),
            "original_model_margin": round(home - away, 4),
            "shadow_model_margin": round(adj_home - adj_away, 4),
            "original_over_p": round(over_probability(home + away, line, sigma), 6),
            "shadow_over_p": round(over_probability(adj_home + adj_away, line, sigma), 6),
            "disposition": "RESEARCH_ONLY_NO_BET",
        })
    return {
        "schema": SCHEMA,
        "source_card_schema": card["schema"],
        "source_model_status": card.get("model_status"),
        "calibration_schema": calibration["schema"],
        "offset_points": offset,
        "evidence_class": "SHADOW_RESEARCH_NOT_FOR_STAKING",
        "bet_count": 0, "bets_enabled": False,
        "validated_markets": [],
        "production_changed": False,
        "games": shadows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = shadow_card(json.loads(args.card.read_text()), json.loads(args.calibration.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("CFB_TOTAL_SHADOW_RESEARCH_ONLY games=%d offset=%+.3f no_bets=1" %
          (len(report["games"]), report["offset_points"]))


if __name__ == "__main__":
    main()
