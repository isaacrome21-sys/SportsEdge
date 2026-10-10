#!/usr/bin/env python3
"""Render the NFL phone card: picks/leans with prices and edges, plus retrieved reasons."""
from __future__ import annotations

import argparse
from pathlib import Path
import json

from sportsedge.nfl_attempt9_live_forecast import (
    NO_MODEL_HISTORY,
    NO_MODEL_INTEGER,
    NO_MODEL_MARKET,
    NO_MODEL_MONEYLINE,
    NO_MODEL_SPREAD,
    market_eligibility,
)
# research_notes/nfl_team_total_prop_backtest_20261003.md
TEAM_TOTAL_NOTE = (
    "TRACK ONLY (not a bet): team totals tested, no edge "
    "(51.5% OOS 2018-26 vs closing implied team total; breakeven 52.4%)"
)
PROP_NOTE = (
    "TRACK ONLY (not a bet): no free historical prop closing lines, "
    "so props can't be backtested"
)


def fmt_price(price: object) -> str:
    try:
        value = int(price)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(price)
    return f"+{value}" if value > 0 else str(value)


def _track_note(row: dict) -> str | None:
    if row.get("player"):
        return PROP_NOTE
    if str(row.get("market")) == "team_total":
        return TEAM_TOTAL_NOTE
    return None


def both_side_section(engine: dict) -> str:
    """Quoted both sides (collapsed for phones), then unquoted catalog families. Not a bet list."""
    board = engine.get("full_board") or {}
    rows = list(board.get("rows") or [])
    if not rows:
        from sportsedge.football_full_board import board_from_machine_results, catalog_complete
        from scripts.run_nfl_lines_card import _board_rows_from_games

        board = board_from_machine_results("NFL", _board_rows_from_games(engine.get("games") or []))
        engine["full_board"] = board
        summary = dict(engine.get("summary") or {})
        summary["both_sides"] = board["summary"]["both_sides"]
        summary["catalog_complete"] = catalog_complete(board["summary"])
        summary["side_rows"] = board["summary"]["side_rows"]
        summary["total_rows"] = board["summary"]["total_rows"]
        summary["prop_rows"] = board["summary"]["prop_rows"]
        engine["summary"] = summary
        rows = list(board.get("rows") or [])
    # Only rows tied to a pasted game. Game-less catalog placeholders are named in one line below.
    quoted = [row for row in rows if row.get("game_id") and row.get("reason") != "NO_QUOTE_OR_ENGINE_ROW"]
    priced = [row for row in quoted if row.get("american_odds") is not None]
    unpriced = [row for row in quoted if row.get("american_odds") is None]
    missing = sorted({
        str(row.get("market") or "") for row in rows
        if not row.get("game_id") or row.get("reason") == "NO_QUOTE_OR_ENGINE_ROW"
    } - {str(row.get("market") or "") for row in priced})
    lines = [
        "",
        f"<details><summary>Both sides of every pasted line ({len(priced)} rows, track only)</summary>",
        "",
        "| game | market | player/team | side | line | odds |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    priced.sort(key=lambda row: (str(row.get("game_id") or ""), str(row.get("market") or ""), str(row.get("entity_id") or ""), str(row.get("selection") or row.get("side") or "")))
    for row in priced:
        lines.append(
            "| {game} | {market} | {entity} | {side} | {line} | {odds} |".format(
                game=row.get("game_id") or "",
                market=row.get("market") or "",
                entity=row.get("entity_id") or "",
                side=row.get("selection") or row.get("side") or "",
                line="" if row.get("line") is None else row.get("line"),
                odds=fmt_price(row.get("american_odds")),
            )
        )
    if not priced:
        lines.append("| | | | | | No quoted props, sides, or totals |")
    if unpriced:
        lines += ["", f"{len(unpriced)} opposite side(s) had no price in the paste, so they are blocked."]
    if missing:
        lines += ["", "Not pasted (blocked, not priced): " + ", ".join(m for m in missing if m)]
    lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


NO_MODEL_TEXT = {
    NO_MODEL_MONEYLINE: "no pick: no moneyline model yet",
    NO_MODEL_SPREAD: "no pick: spreads held until a margin model is validated",
    NO_MODEL_INTEGER: "no pick: whole-number line needs a push model",
    NO_MODEL_HISTORY: "no pick: not enough prior games for one team",
    NO_MODEL_MARKET: "no pick: market not modeled",
}


def _plain_reason(code: str) -> str:
    return NO_MODEL_TEXT.get(str(code), str(code))


def _market_label(row: dict, away: str, home: str) -> str:
    market = str(row.get("market") or "")
    a = fmt_price(row.get("away_or_over_price"))
    h = fmt_price(row.get("home_or_under_price"))
    line = row.get("line")
    if market == "moneyline":
        return f"ML {away} {a} / {home} {h}"
    if market == "spread" and line is not None:
        ln = float(line)
        return f"Spread {away} {ln:+g} {a} / {home} {-ln:+g} {h}"
    if market == "total" and line is not None:
        return f"Total {float(line):g} o{a} / u{h}"
    return str(row.get("raw") or market)


def why_lines(game: dict) -> list[str]:
    """Reasons behind the card. Only facts this run actually retrieved; nothing else is printed."""
    ctx = game.get("context") or {}
    away, home = str(game.get("away")), str(game.get("home"))
    out: list[str] = []
    proj = ctx.get("projection")
    if proj:
        margin = float(proj["home_margin"])
        fav = home if margin >= 0 else away
        out.append(f"- Model (Attempt 9): total {proj['total']:g}, {fav} by {abs(margin):g}")
        out.append(
            f"- Recent scoring, weighted last 10: {away} {proj['away_pf']:g} for / {proj['away_pa']:g} against; "
            f"{home} {proj['home_pf']:g} / {proj['home_pa']:g}"
        )
    qbs = ctx.get("last_start_qb") or {}
    if qbs:
        parts = [f"{team} {qbs[team]['qb']} ({qbs[team]['date'][5:]})" for team in (away, home) if team in qbs]
        out.append("- Last listed starting QB (nflverse): " + "; ".join(parts))
    if ctx.get("qb_change_flag"):
        out.append(
            "- QB check: DK has passing props for " + ", ".join(ctx["qb_change_flag"])
            + ", who was not either team's last starter. Possible QB change; confirm before using any lean."
        )
    if out:
        out.insert(0, "Why (from " + ", ".join(ctx.get("sources") or ["retrieved data"]) + "):")
        out.append("- Injuries/inactives: not checked by this card.")
    return out


def render(engine: dict) -> str:
    games = engine.get("games") or []
    title = " · ".join(f"{g.get('away')} @ {g.get('home')}" for g in games[:3])
    if len(games) > 3:
        title += f" +{len(games) - 3} more"
    lines = [f"**NFL card** — {title or 'no games'}", ""]
    if not any(g.get("picks") for g in games) and engine.get("empty_reason"):
        lines += [str(engine["empty_reason"]), ""]
    for game in games:
        away, home = str(game.get("away")), str(game.get("home"))
        lines.append(f"### {away} @ {home}")
        picks_out: list[str] = []
        other: list[str] = []
        team_totals: list[str] = []
        props: list[str] = []
        for row in game.get("markets") or []:
            label = _market_label(row, away, home)
            note = _track_note(row)
            if note == PROP_NOTE:
                props.append(f"  - {label}")
                continue
            if note == TEAM_TOTAL_NOTE:
                team_totals.append(f"  - {label}")
                continue
            reason = row.get("no_model") or market_eligibility(row.get("market"), row.get("line"))
            if reason:
                other.append(f"- {label}: {_plain_reason(reason)}")
                continue
            pick = row.get("pick")
            lean = row.get("lean")
            if pick:
                picks_out.append(
                    f"- **BET** {pick['selection']} {pick.get('line', '')} @ {fmt_price(pick['price_american'])}"
                    f" · EV {pick.get('ev_per_dollar', 0) * 100:+.1f}%"
                    f" · edge {pick.get('edge_probability_points', 0) * 100:+.1f} pts vs no-vig"
                )
            elif lean:
                picks_out.append(
                    f"- LEAN (no proven edge, not a bet): {lean['selection']} {lean.get('line', '')} @ {fmt_price(lean['price_american'])}"
                    f" · model EV {lean.get('ev_per_dollar', 0) * 100:+.1f}%"
                    f" · edge {lean.get('edge_probability_points', 0) * 100:+.1f} pts vs no-vig"
                )
            else:
                other.append(f"- {label}: no lean (model edge under 2% EV)")
        lines += picks_out + other
        if team_totals:
            lines.append(f"- Team totals ({len(team_totals)}): {TEAM_TOTAL_NOTE}")
            lines += team_totals
        if props:
            lines += [
                "",
                f"<details><summary>Props ({len(props)}): TRACK ONLY (not a bet)</summary>",
                "",
                f"{PROP_NOTE}",
                "",
                *props,
                "",
                "</details>",
            ]
        why = why_lines(game)
        if why:
            lines += [""] + why
        lines.append("")
    if any(g.get("leans") for g in games):
        lines.append("Leans: Attempt 9 totals hit 49.7% out of sample vs closing lines (breakeven 52.4%). Track only.")
    lines.append(both_side_section(engine))
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-output", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--pre-context", action="store_true", help="kept for workflow compatibility; no effect on wording")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    engine = json.loads(Path(args.engine_output).read_text(encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text(render(engine), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
