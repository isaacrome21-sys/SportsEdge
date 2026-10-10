#!/usr/bin/env python3
"""Diagnostic only: flag systematic CFB model-vs-market totals disagreements.

This is NOT calibration, a new probability model, or a bet promotion gate.
It retains rejected/raw model estimates so an operator can investigate the
forecast family before relying on its apparent EV. No historical backfill.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCHEMA = "CFB_SDV_TOTAL_BIAS_AUDIT_V1"
MIN_GAMES = 3
MIN_POINT_GAP = 5.0


def audit(payload):
    if payload.get("schema") != "CFB_SDV_CARD_V2":
        raise ValueError("CFB_SDV_TOTAL_AUDIT_CARD_SCHEMA_INVALID")
    if not isinstance(payload.get("results"), list):
        raise ValueError("CFB_SDV_TOTAL_AUDIT_RESULTS_REQUIRED")

    over_by_matchup = {}
    for row in payload["results"]:
        if (row.get("market") != "TOTAL" or row.get("side") != "OVER" or
                row.get("devig") != "PAIRED_PROPORTIONAL"):
            continue
        matchup = str(row.get("matchup") or row.get("game_id") or "")
        if not matchup:
            raise ValueError("CFB_SDV_TOTAL_AUDIT_GAME_REQUIRED")
        if matchup in over_by_matchup:
            raise ValueError("CFB_SDV_TOTAL_AUDIT_DUPLICATE_TOTAL:" + matchup)
        try:
            mean_home = float(row["home_mean"])
            mean_away = float(row["away_mean"])
            line = float(row["line"])
            edge = float(row["edge"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("CFB_SDV_TOTAL_AUDIT_NUMERIC_INVALID") from exc
        gap = mean_home + mean_away - line
        over_by_matchup[matchup] = {
            "matchup": matchup,
            "model_total": round(mean_home + mean_away, 2),
            "market_total": line,
            "model_minus_market_points": round(gap, 2),
            "raw_over_edge_pp": round(100 * edge, 2),
            "underlying_status": row.get("bet_status"),
            "reason": row.get("reason"),
        }

    rows = sorted(over_by_matchup.values(), key=lambda r: r["matchup"])
    n = len(rows)
    over = sum(r["model_minus_market_points"] >= MIN_POINT_GAP for r in rows)
    under = sum(r["model_minus_market_points"] <= -MIN_POINT_GAP for r in rows)
    directional_skew = (n >= MIN_GAMES and (over == n or under == n))
    all_anomalous = (n >= MIN_GAMES and all(
        r["reason"] == "EDGE_TOO_LARGE_SUSPECT" and r["underlying_status"] == "PASS"
        for r in rows
    ))
    return {
        "schema": SCHEMA,
        "model_status": payload.get("model_status"),
        "capture_time": (payload.get("live_source_provenance") or {}).get("capture_time"),
        "source_contract": (payload.get("live_source_provenance") or {}).get("source_contract"),
        "games_with_paired_totals": n,
        "model_over_by_5_or_more": over,
        "model_under_by_5_or_more": under,
        "mean_model_minus_market_points": round(
            sum(r["model_minus_market_points"] for r in rows) / n, 2
        ) if n else None,
        "directional_bias_signal": "MODEL_HIGH" if directional_skew and over == n else (
            "MODEL_LOW" if directional_skew and under == n else "NONE"
        ),
        "all_large_edges_rejected": all_anomalous,
        "research_review_required": bool(directional_skew and all_anomalous),
        "authority": {
            "model_validated": False,
            "bets_created": False,
            "promotions_enabled": False,
            "official_authority": False,
        },
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = audit(json.loads(args.card.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"CFB_SDV_TOTAL_BIAS_AUDIT games={report['games_with_paired_totals']} "
          f"signal={report['directional_bias_signal']} "
          f"mean_gap={report['mean_model_minus_market_points']} "
          f"review={report['research_review_required']}")


if __name__ == "__main__":
    main()
