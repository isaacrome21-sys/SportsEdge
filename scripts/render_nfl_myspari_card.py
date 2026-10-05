#!/usr/bin/env python3
"""Render the NFL phone card. PRE-CONTEXT heading until context is bound."""
from __future__ import annotations

import argparse
from pathlib import Path
import json

from sportsedge.nfl_attempt9_live_forecast import market_eligibility
from sportsedge.sports.nfl.attempt9_model_p import model_probability
from sportsedge.nfl_attempt9_live_forecast import load_model_p

PRE_CONTEXT = "PRE-CONTEXT · NOT FINAL"
FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
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
    """Quoted both sides, then unquoted catalog families. Not a bet list."""
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
    summary = board.get("summary") or engine.get("summary") or {}
    quoted = [row for row in rows if row.get("reason") != "NO_QUOTE_OR_ENGINE_ROW"]
    missing = sorted({str(row.get("market") or "") for row in rows if row.get("reason") == "NO_QUOTE_OR_ENGINE_ROW"})
    lines = [
        "",
        "All props, sides, and totals",
        f"both_sides={summary.get('both_sides')} catalog_complete={summary.get('catalog_complete')} "
        f"sides={summary.get('side_rows')} totals={summary.get('total_rows')} props={summary.get('prop_rows')}",
        "TRACK ONLY. Both offered sides are listed. A missing quote is BLOCKED, not omitted. Not a bet.",
        "",
        "| game | market | entity | side | line | odds | note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    quoted.sort(key=lambda row: (str(row.get("game_id") or ""), str(row.get("market") or ""), str(row.get("entity_id") or ""), str(row.get("selection") or row.get("side") or "")))
    for row in quoted:
        lines.append(
            "| {game} | {market} | {entity} | {side} | {line} | {odds} | {note} |".format(
                game=row.get("game_id") or "",
                market=row.get("market") or "",
                entity=row.get("entity_id") or "",
                side=row.get("selection") or row.get("side") or "",
                line="" if row.get("line") is None else row.get("line"),
                odds="" if row.get("american_odds") is None else row.get("american_odds"),
                note="Price needed" if row.get("american_odds") is None else "TRACK ONLY",
            )
        )
    if not quoted:
        lines.append("| | | | | | | No quoted props, sides, or totals |")
    if missing:
        lines += ["", "Unquoted catalog families (both sides BLOCKED, not omitted): " + ", ".join(missing)]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-output", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--pre-context", action="store_true")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    engine = json.loads(Path(args.engine_output).read_text(encoding="utf-8"))
    heading = PRE_CONTEXT if args.pre_context or not engine.get("context_bound") else "card"
    lines = [f"NFL — {heading}", ""]
    for game in engine.get("games") or []:
        lines.append(f"{game.get('away')} @ {game.get('home')}")
        for row in game.get("markets") or []:
            reason = row.get("no_model") or market_eligibility(row.get("market"), row.get("line"))
            note = _track_note(row)
            if note:
                lines.append(f"- {row.get('raw') or row.get('market')}: {note}")
                continue
            if reason:
                lines.append(f"- {row.get('raw') or row.get('market')}: {reason}")
                continue
            pick = row.get("pick")
            lean = row.get("lean")
            if not pick and lean:
                lines.append(
                    f"- LEAN (no proven edge, not a bet): {lean['selection']} {lean.get('line', '')} @ {fmt_price(lean['price_american'])}"
                    f"  model EV {lean.get('ev_per_dollar', 0):+.3f}"
                )
                continue
            if not pick:
                lines.append(f"- {row.get('market')}: no pick")
                continue
            lines.append(
                f"- {pick['selection']} {pick.get('line', '')} @ {fmt_price(pick['price_american'])}"
                f"  Score-B {pick.get('score_0_100', '—')}"
                f"  EV {pick.get('ev_per_dollar', 0):+.3f}"
            )
        lines.append("")
    if not any(g.get("picks") for g in engine.get("games") or []):
        if engine.get("empty_reason"):
            lines.append(str(engine["empty_reason"]))
    if any(g.get("leans") for g in engine.get("games") or []):
        lines.append("Leans: Attempt 9 totals hit 49.7% out of sample vs closing lines (breakeven 52.4%). Track only.")
    lines.append(FOOTER)
    lines.append(both_side_section(engine))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
