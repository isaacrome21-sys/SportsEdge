#!/usr/bin/env python3
"""Phone render for a football card that lists both sides of every prop, side, and total."""
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
    from sportsedge.football_full_board import catalog_complete, emit_all_props_side_totals

    sport = str(payload.get("sport") or report.get("sport") or "NFL").upper()
    if sport not in {"NFL", "CFB"}:
        sport = "NFL"
    source = payload.get("results") or payload.get("rows") or []
    if not isinstance(source, list) and isinstance(report, dict):
        source = report.get("results") or []
    game_rows = [row for row in source if isinstance(row, dict)]
    board = emit_all_props_side_totals(sport=sport, game_rows=game_rows)
    payload["full_board"] = board
    card_summary = dict(payload.get("summary") or {})
    card_summary["both_sides"] = board["summary"]["both_sides"]
    card_summary["side_rows"] = board["summary"]["side_rows"]
    card_summary["total_rows"] = board["summary"]["total_rows"]
    card_summary["prop_rows"] = board["summary"]["prop_rows"]
    card_summary["catalog_complete"] = catalog_complete(board["summary"])
    payload["summary"] = card_summary
    return board


def render_markdown(payload: dict) -> str:
    board = _board(payload)
    summary = payload.get("summary") or board.get("summary") or {}
    lines = [
        f"SportsEdge {payload.get('sport') or board.get('sport') or 'FOOTBALL'} props, sides, and totals",
        f"run_status={payload.get('run_status') or payload.get('status')} both_sides={summary.get('both_sides')} catalog_complete={summary.get('catalog_complete')}",
        f"sides={summary.get('side_rows')} totals={summary.get('total_rows')} props={summary.get('prop_rows')}",
        "",
        "Both sides are listed. A missing quote is BLOCKED, not omitted. Complements are priced only from a supplied opposite quote.",
        "NOT Model_P / NOT Truth Gate / NOT OFFICIAL.",
        "",
        "| lane | market | side | line | odds | model_p | status | reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = list(board.get("rows") or [])
    rows.sort(key=lambda row: (str(row.get("lane") or ""), str(row.get("market") or ""), str(row.get("selection") or row.get("side") or "")))
    for row in rows:
        model_p = row.get("model_p")
        lines.append(
            "| {lane} | {market} | {side} | {line} | {odds} | {model_p} | {status} | {reason} |".format(
                lane=row.get("lane") or "",
                market=row.get("market") or "",
                side=row.get("selection") or row.get("side") or "",
                line="" if row.get("line") is None else row.get("line"),
                odds="" if row.get("american_odds") is None else row.get("american_odds"),
                model_p="" if model_p is None else round(float(model_p), 4),
                status=row.get("presentation") or "",
                reason=row.get("reason") or "",
            )
        )
    if not rows:
        lines.append("|  |  |  |  |  |  |  | no board rows |")
    lines.append("")
    lines.append("Prop engines remain NO_ENGINE until independently validated. This card does not grant staking authority.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-output", default="artifacts/live_nfl_card.json")
    parser.add_argument("--out-dir", default="artifacts/nfl_myspari")
    args = parser.parse_args()
    payload = json.loads(Path(args.engine_output).read_text(encoding="utf-8"))
    text = render_markdown(payload)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text(text, encoding="utf-8")
    board = _board(payload)
    (out / "card.json").write_text(
        json.dumps({"summary": payload.get("summary") or board.get("summary") or {}, "rows": board.get("rows") or []}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
