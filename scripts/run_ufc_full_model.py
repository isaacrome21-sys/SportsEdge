#!/usr/bin/env python3
"""Run SportsEdge UFC full model against live or auditable snapshot MMA odds.

Input fighter snapshots are JSON to keep the runtime deterministic and auditable.
A trained artifact is not sufficient for official betting: production bets require
explicit promotion evidence. Unpromoted models still emit candidates/diagnostics,
but the official bets array remains empty.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sportsedge.ufc_engine import FighterSnapshot, FightContext
from sportsedge.ufc_runtime import (
    enforce_model_promotion,
    evaluate_h2h,
    load_artifact,
    load_promotion_evidence,
    write_card,
)
from sportsedge.ufc_source import OddsQuote, fetch_live_mma_odds, normalize_name


def _load_fighters(path: str) -> list[FighterSnapshot]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload["fighters"] if isinstance(payload, dict) else payload
    return [FighterSnapshot(**row) for row in rows]


def _load_contexts(path: str | None):
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for row in payload:
        key = frozenset((normalize_name(row["fighter_a"]), normalize_name(row["fighter_b"])))
        out[key] = FightContext(
            rounds=int(row.get("rounds", 3)),
            title_fight=bool(row.get("title_fight", False)),
            short_notice_days=row.get("short_notice_days"),
            altitude_ft=float(row.get("altitude_ft", 0.0)),
        )
    return out


def _load_odds_snapshot(path: str) -> list[OddsQuote]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("quotes", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("UFC_ODDS_SNAPSHOT_INVALID")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(OddsQuote(**row))
    if not out:
        raise SystemExit("UFC_ODDS_SNAPSHOT_EMPTY")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fighters", required=True)
    ap.add_argument("--contexts")
    ap.add_argument("--model-artifact")
    ap.add_argument("--promotion-evidence")
    ap.add_argument("--odds-json", help="Auditable odds snapshot; when omitted, fetch live odds from The Odds API")
    ap.add_argument("--output", default="artifacts/ufc_card.json")
    ap.add_argument("--bookmakers", default="draftkings")
    ap.add_argument("--min-edge", type=float, default=0.025)
    ap.add_argument("--min-ev", type=float, default=0.03)
    ap.add_argument("--max-uncertainty", type=float, default=0.20)
    ap.add_argument("--sims", type=int, default=250000)
    args = ap.parse_args()

    fighters = _load_fighters(args.fighters)
    contexts = _load_contexts(args.contexts)
    artifact = load_artifact(args.model_artifact) if args.model_artifact else None
    promotion = load_promotion_evidence(args.promotion_evidence)

    if args.odds_json:
        quotes = _load_odds_snapshot(args.odds_json)
    else:
        api_key = os.environ.get("ODDS_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("ODDS_API_KEY is required when --odds-json is not supplied")
        quotes = fetch_live_mma_odds(
            api_key=api_key,
            bookmakers=tuple(x.strip() for x in args.bookmakers.split(",") if x.strip()),
        )

    candidates = evaluate_h2h(
        fighters=fighters,
        quotes=quotes,
        contexts=contexts,
        artifact=artifact,
        min_edge=args.min_edge,
        min_ev=args.min_ev,
        max_uncertainty=args.max_uncertainty,
        n_sims=args.sims,
    )
    candidates = enforce_model_promotion(candidates, promotion)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    write_card(args.output, candidates, promotion_evidence=promotion)
    for c in candidates:
        print(
            f"{c.fighter} vs {c.opponent}: p={c.model_probability:.3f} odds={c.odds:+d} "
            f"edge={c.edge:.3f} ev={c.ev:.3f} {'BET' if c.passed else 'PASS'} reason={c.reason}"
        )
    print(
        json.dumps(
            {
                "promotion_status": promotion.get("status", "UNVERIFIED"),
                "promotion_blockers": promotion.get("blockers", []),
                "official_bets": sum(1 for c in candidates if c.passed),
                "candidates": len(candidates),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
