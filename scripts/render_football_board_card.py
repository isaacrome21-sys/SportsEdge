#!/usr/bin/env python3
"""Phone render for a football card — sides, totals, alt lines, props, SGP legs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _board(payload: dict) -> dict:
    board = payload.get("full_board") or payload.get("all_props_side_totals") or {}
    if board.get("rows"):
        return board
    report = payload.get("report") or {}
    summary = report.get("summary") if isinstance(report, dict) else {}
    nested = None
    if isinstance(summary, dict):
        nested = summary.get("full_board") or summary.get("all_props_side_totals")
    if isinstance(nested, dict) and nested.get("rows"):
        return nested
    from sportsedge.football_full_board import board_from_machine_results, catalog_complete

    sport = str(payload.get("sport") or report.get("sport") or "NFL").upper()
    if sport not in {"NFL", "CFB"}:
        sport = "NFL"
    source = payload.get("results") or payload.get("rows") or report.get("results") or []
    if not isinstance(source, list):
        source = []
    game_rows = [row for row in source if isinstance(row, dict)]
    board = board_from_machine_results(sport, game_rows)
    payload["full_board"] = board
    card_summary = dict(payload.get("summary") or {})
    card_summary["both_sides"]      = board["summary"]["both_sides"]
    card_summary["side_rows"]       = board["summary"]["side_rows"]
    card_summary["total_rows"]      = board["summary"]["total_rows"]
    card_summary["prop_rows"]       = board["summary"]["prop_rows"]
    card_summary["catalog_complete"] = catalog_complete(board["summary"])
    payload["summary"] = card_summary
    return board


def _display_note(row: dict) -> str:
    if row.get("sgp_leg"):
        return "Combination cannot be evaluated yet"
    if row.get("american_odds") is None:
        return "Price needed"
    if row.get("model_p") is None:
        return "Cannot evaluate yet"
    return "Research estimate"


def _fmt_board_row(row: dict) -> str:
    # Scores must arrive from the scoring system; probability is not a score.
    score = row.get("score")
    return "| {game} | {market} | {side} | {line} | {odds} | {score} | {note} |".format(
        game=row.get("game_id") or "",
        market=row.get("market") or "",
        side=row.get("selection") or row.get("side") or "",
        line="" if row.get("line") is None else row["line"],
        odds="" if row.get("american_odds") is None else row["american_odds"],
        score="—" if score is None else score,
        note=_display_note(row),
    )


def render_markdown(payload: dict) -> str:
    board = _board(payload)
    lines = [
        f"SportsEdge {payload.get('sport') or board.get('sport') or 'FOOTBALL'}",
        "",
        "| Game | Market | Pick | Line | Price | Score / 100 | Note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    candidates = payload.get("research_leans") or []
    if candidates:
        lines[2:2] = ["Top price comparisons", ""]
        lines.extend(_fmt_board_row(row) for row in candidates)
        lines += ["", "Full market board", "", "| Game | Market | Pick | Line | Price | Score / 100 | Note |", "| --- | --- | --- | --- | --- | --- | --- |"]
    board_rows = sorted(board.get("rows") or [], key=lambda r: (
        str(r.get("game_id") or ""), str(r.get("market") or ""),
        float(r.get("line") or 0), str(r.get("selection") or r.get("side") or ""),
    ))
    lines.extend(_fmt_board_row(row) for row in board_rows)
    if not board_rows:
        lines.append("| | | | | | | No prices supplied |")
    if payload.get("sgp_legs"):
        lines += ["", "SGP legs", "", "Individual legs do not establish a combination's probability.", "",
                  "| Game | Market | Pick | Line | Price | Score / 100 | Note |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        lines.extend(_fmt_board_row({**leg, "sgp_leg": True}) for leg in payload["sgp_legs"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-output", default="artifacts/live_nfl_card.json")
    parser.add_argument("--out-dir",       default="artifacts/nfl_myspari")
    args = parser.parse_args()
    payload = json.loads(Path(args.engine_output).read_text(encoding="utf-8"))
    text = render_markdown(payload)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text(text, encoding="utf-8")
    board = _board(payload)
    (out / "card.json").write_text(
        json.dumps({
            "summary":  payload.get("summary") or board.get("summary") or {},
            "sgp_legs": payload.get("sgp_legs") or [],
            "rows":     board.get("rows") or [],
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
