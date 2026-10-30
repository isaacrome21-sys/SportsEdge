#!/usr/bin/env python3
"""NHL phone card from the frozen rate v1 owner.

A market may say BET only if it is listed in VALIDATED_BET_MARKETS, which is
filled only after an out-of-sample backtest vs closing lines beats 52.4% at
-110 / positive EV vs no-vig. Until then every positive-EV side is a LEAN.
Moneyline stays held (home-ice bias unvalidated).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.quote_freshness import QUOTE_STALE, check_quote_freshness, is_fresh
from sportsedge.nhl_rate_v1_card import (
    ev_return,
    final_score_distribution,
    no_vig,
    puck_line_probs,
    total_probs,
)
from sportsedge.sports.nhl.market_capabilities import capability_for

PRE_CONTEXT = "PRE-CONTEXT · NOT FINAL"
FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
PRICED = {"PUCK_LINE", "TOTAL"}
FLOOR = 0.02
# Owner ruling 2026-10-25: max 30 minutes from actual DK Captured time.
QUOTE_MAX_AGE_SECONDS = 1800
ML_HOLD = "NO_MODEL:HOME_ICE_UNVALIDATED"
# Empty on purpose: add a market only with a linked OOS closing-line backtest.
VALIDATED_BET_MARKETS: frozenset[str] = frozenset()


def _side(name: str, market: str, win_p: float, push_p: float, odds: int, fair_p: float) -> str:
    ret = ev_return(win_p, odds, push_p)
    graded = win_p / max(1e-9, 1.0 - push_p)
    edge = graded - fair_p
    if ret >= FLOOR:
        tag = "BET" if market in VALIDATED_BET_MARKETS else "LEAN"
    else:
        tag = "PASS"
    return f"{name} {odds:+d} p={graded:.3f} nv={fair_p:.3f} edge={edge:+.1%} ret={ret:+.1%} {tag}"


def quote_refusal(captured_at: str | None, *, as_of: datetime) -> str | None:
    """None only for a real, timezone-aware quote no older than 30 minutes."""
    evidence = check_quote_freshness(
        captured_at, now=as_of, max_age_seconds=QUOTE_MAX_AGE_SECONDS,
    )
    if is_fresh(evidence):
        return None
    if evidence["code"] == QUOTE_STALE:
        return "QUOTE_STALE_OVER_1800S"
    return str(evidence["code"])


def ledger_rows(ticket: dict, *, as_of: datetime | None = None) -> list[dict]:
    """Pregame pick records for the CLV/grade pipeline. Fail closed.

    One row per priced side whose EV clears FLOOR. Rows carry the DK price and
    the board's own ``captured_at``; a game without one logs nothing (never the
    issue time). Tag stays LEAN unless the market is in VALIDATED_BET_MARKETS.
    Grading and closing capture are separate steps; these rows start ungraded.
    """
    as_of = as_of if as_of is not None else datetime.now(timezone.utc)
    rows: list[dict] = []
    for game in ticket.get("games") or []:
        away, home = str(game.get("away") or ""), str(game.get("home") or "")
        captured = game.get("captured_at")
        if quote_refusal(captured, as_of=as_of) is not None:
            continue
        fsd = final_score_distribution(away, home)
        if fsd is None:
            continue
        for m in game.get("markets") or []:
            market, line = str(m.get("market")), m.get("line")
            if market not in PRICED or line is None:
                continue
            a_odds, h_odds = int(m["away_or_over_price"]), int(m["home_or_under_price"])
            fair_a, fair_h = no_vig(a_odds, h_odds)
            if market == "TOTAL":
                pa, push, ph = total_probs(fsd, float(line))
                sides = (("OVER", pa, a_odds, fair_a), ("UNDER", ph, h_odds, fair_h))
            else:
                pa, push, ph = puck_line_probs(fsd, float(line))
                sides = ((f"AWAY {float(line):+g}", pa, a_odds, fair_a),
                         (f"HOME {-float(line):+g}", ph, h_odds, fair_h))
            for side, win_p, odds, fair in sides:
                ret = ev_return(win_p, odds, push)
                if ret < FLOOR:
                    continue
                rows.append({
                    "sport": "NHL", "slate": ticket.get("slate"), "issue": ticket.get("issue"),
                    "away": away, "home": home, "market": market, "line": float(line),
                    "side": side, "price": odds, "captured_at": captured,
                    "model_p": round(win_p, 6), "push_p": round(push, 6),
                    "no_vig_p": round(fair, 6), "ev": round(ret, 6),
                    "tag": "BET" if market in VALIDATED_BET_MARKETS else "LEAN",
                    "owner": "nhl_rate_v1", "result": None, "close_price": None, "clv": None,
                })
    rows.sort(key=lambda r: -r["ev"])
    return rows


def price_row(market: str, line, away_odds, home_odds, fsd: dict | None) -> str:
    cap = capability_for(market)
    if cap.status == "NO_ENGINE":
        return f"NO_MODEL:{cap.reason}"
    if market == "MONEYLINE":
        return ML_HOLD
    if market not in PRICED:
        return "NO_MODEL:NOT_IN_RATE_V1"
    if fsd is None:
        return "NO_MODEL:TEAM_PRIOR_MISSING"
    if line is None:
        return "NO_MODEL:LINE_MISSING"
    a_odds, h_odds = int(away_odds), int(home_odds)
    fair_a, fair_h = no_vig(a_odds, h_odds)
    if market == "TOTAL":
        over, push, under = total_probs(fsd, float(line))
        return (
            f"{_side('over', market, over, push, a_odds, fair_a)} | "
            f"{_side('under', market, under, push, h_odds, fair_h)}"
        )
    away, push, home = puck_line_probs(fsd, float(line))
    return (
        f"{_side(f'away {float(line):+g}', market, away, push, a_odds, fair_a)} | "
        f"{_side(f'home {-float(line):+g}', market, home, push, h_odds, fair_h)}"
    )


def render_lines(ticket: dict, *, as_of: datetime, pre_context: bool = False) -> list[str]:
    """Render only from current source-captured quotes; never use issue edit time."""
    heading = PRE_CONTEXT if pre_context else "card"
    lines = [f"NHL — {heading}", ""]
    for game in ticket.get("games") or []:
        away = str(game.get("away") or "")
        home = str(game.get("home") or "")
        lines.append(f"{away} @ {home}")
        refusal = quote_refusal(game.get("captured_at"), as_of=as_of)
        fsd = final_score_distribution(away, home) if refusal is None else None
        for row in game.get("markets") or []:
            priced = refusal if refusal is not None else price_row(
                str(row.get("market")),
                row.get("line"),
                row.get("away_or_over_price"),
                row.get("home_or_under_price"),
                fsd,
            )
            lines.append(f"- {row.get('raw') or row.get('market')}: {priced}")
        lines.append("")
    validated = ", ".join(sorted(VALIDATED_BET_MARKETS)) or "none yet"
    lines.append(f"Validated bet markets: {validated}. Everything else is LEAN at most.")
    lines.append("p = model win prob (push excluded) · nv = no-vig market prob · ret = EV per $1")
    lines.append("ML held (home-ice unvalidated). Props NO_MODEL.")
    lines.append(FOOTER)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--pre-context", action="store_true")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    ticket = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    # One real render-time clock for both the displayed card and saved picks.
    # Delayed GitHub issue edits can never refresh the sportsbook capture time.
    as_of = datetime.now(timezone.utc)
    lines = render_lines(ticket, as_of=as_of, pre_context=args.pre_context)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "picks.json").write_text(
        json.dumps(ledger_rows(ticket, as_of=as_of), indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
