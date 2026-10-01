#!/usr/bin/env python3
"""NHL phone card. Frozen rate v1 prices supported totals (and puck line as lean)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.nhl_rate_v1_card import ev_return, simulate_matchup
from sportsedge.sports.nhl.market_capabilities import capability_for

PRE_CONTEXT = "PRE-CONTEXT · NOT FINAL"
FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
PRICED = {"PUCK_LINE", "TOTAL"}
FLOOR = 0.02
ML_HOLD = "NO_MODEL:HOME_ICE_UNVALIDATED"
TOTAL_LINE_HOLD = "NO_MODEL:TOTAL_LINE_UNSUPPORTED_PUSH_OR_GRID"
SUPPORTED_TOTAL_KEYS = {5.5: "over_5_5", 6.5: "over_6_5"}


def _label(model_p: float | None, odds: int | None) -> str:
    if model_p is None:
        return "NO_MODEL"
    if odds is None:
        return f"model_p={model_p:.3f} LEAN"
    ret = ev_return(model_p, odds)
    tag = "PLAY" if ret >= FLOOR else "PASS"
    return f"model_p={model_p:.3f} ret={ret:+.1%} {tag}"


def _supported_total_key(line) -> str | None:
    """Bind only to total events actually emitted by the frozen v1 simulation.

    Whole-number totals require explicit push mass. Other half-point lines require
    their own simulated event rather than borrowing 5.5 or 6.5 probabilities.
    """
    try:
        value = float(line)
    except (TypeError, ValueError):
        return None
    return SUPPORTED_TOTAL_KEYS.get(value)


def price_row(market: str, line, away_odds, home_odds, sim: dict | None) -> str:
    cap = capability_for(market)
    if cap.status == "NO_ENGINE":
        return f"NO_MODEL:{cap.reason}"
    if market == "MONEYLINE":
        return ML_HOLD
    if market not in PRICED:
        return "NO_MODEL:NOT_IN_RATE_V1"
    if sim is None:
        return "NO_MODEL:TEAM_PRIOR_MISSING"
    if market == "TOTAL":
        key = _supported_total_key(line)
        if key is None:
            return TOTAL_LINE_HOLD
        over_p = sim[key]
        return f"over {_label(over_p, away_odds)} | under {_label(1.0 - over_p, home_odds)}"
    if market == "PUCK_LINE":
        home_pl = sim["home_pl_minus_1_5"]
        return f"away {_label(1.0 - home_pl, away_odds)} | home {_label(home_pl, home_odds)} (lean)"
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
    lines.append(
        "Owner: NHL_RATE_V1 totals 5.5/6.5 only. Whole-number/other totals fail closed; "
        "ML held (home-ice bias). Props NO_MODEL."
    )
    lines.append(FOOTER)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
