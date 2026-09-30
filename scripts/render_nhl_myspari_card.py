#!/usr/bin/env python3
"""NHL phone card. Frozen rate v1 prices ML / puck line / totals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.nhl_rate_v1_card import ev_return, simulate_matchup
from sportsedge.sports.nhl.market_capabilities import capability_for

PRE_CONTEXT = "PRE-CONTEXT · NOT FINAL"
FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
PRICED = {"MONEYLINE", "PUCK_LINE", "TOTAL"}
FLOOR = 0.02


def _label(market: str, model_p: float | None, odds: int | None, reason: str) -> str:
    if model_p is None:
        return reason
    tag = "NO_MODEL" if reason.startswith("NO_MODEL") else "PASS"
    if odds is not None:
        ret = ev_return(model_p, odds)
        tag = "PLAY" if ret >= FLOOR else "PASS"
        return f"model_p={model_p:.3f} ret={ret:+.1%} {tag}"
    return f"model_p={model_p:.3f} {tag}"


def price_row(market: str, line, away_odds, home_odds, sim: dict | None) -> str:
    cap = capability_for(market)
    if cap.status == "NO_ENGINE":
        return f"NO_MODEL:{cap.reason}"
    if market not in PRICED:
        return "NO_MODEL:NOT_IN_RATE_V1"
    if sim is None:
        return "NO_MODEL:TEAM_PRIOR_MISSING"
    if market == "MONEYLINE":
        # away first, then home, matching intake order
        away = _label(market, sim["away_win"], away_odds, "")
        home = _label(market, sim["home_win"], home_odds, "")
        return f"away {away} | home {home}"
    if market == "TOTAL":
        key = "over_5_5" if line is not None and float(line) <= 6.0 else "over_6_5"
        over_p = sim[key]
        under_p = 1.0 - over_p
        over = _label(market, over_p, away_odds, "")
        under = _label(market, under_p, home_odds, "")
        return f"over {over} | under {under}"
    if market == "PUCK_LINE":
        # away / home two-way. Home -1.5 is sim['home_pl_minus_1_5'] only when home is favorite.
        home_pl = sim["home_pl_minus_1_5"]
        away_pl = 1.0 - home_pl
        away = _label(market, away_pl, away_odds, "")
        home = _label(market, home_pl, home_odds, "")
        return f"away {away} | home {home}"
    return "NO_MODEL:NOT_IN_RATE_V1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--pre-context", action="store_true")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    ticket = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    heading = PRE_CONTEXT if args.pre_context else "card"
    lines = [f"NHL — {heading}", ""]
    for game in ticket.get("games") or []:
        away = str(game.get("away") or "")
        home = str(game.get("home") or "")
        lines.append(f"{away} @ {home}")
        sim = simulate_matchup(away, home)
        for row in game.get("markets") or []:
            priced = price_row(
                str(row.get("market")),
                row.get("line"),
                row.get("away_or_over_price"),
                row.get("home_or_under_price"),
                sim,
            )
            lines.append(f"- {row.get('raw') or row.get('market')}: {priced}")
        lines.append("")
    lines.append("Owner: NHL_RATE_V1_OFFICIAL_STANDIN. Periods and player props stay NO_MODEL.")
    lines.append(FOOTER)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
