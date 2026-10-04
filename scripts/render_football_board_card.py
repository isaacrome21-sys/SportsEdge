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
    card_summary["both_sides"]      = board["summary"]["both_sides"]
    card_summary["side_rows"]       = board["summary"]["side_rows"]
    card_summary["total_rows"]      = board["summary"]["total_rows"]
    card_summary["prop_rows"]       = board["summary"]["prop_rows"]
    card_summary["catalog_complete"] = catalog_complete(board["summary"])
    payload["summary"] = card_summary
    return board


def _fmt_board_row(row: dict) -> str:
    model_p = row.get("model_p")
    edge    = row.get("edge")
    return "| {lane} | {market} | {side} | {line} | {odds} | {mp} | {ed} | {status} | {reason} |".format(
        lane=row.get("lane") or "",
        market=row.get("market") or "",
        side=row.get("selection") or row.get("side") or "",
        line="" if row.get("line") is None else row["line"],
        odds="" if row.get("american_odds") is None else row["american_odds"],
        mp="" if model_p is None else round(float(model_p), 4),
        ed="" if edge is None else round(float(edge), 4),
        status=row.get("presentation") or row.get("bet_status") or "",
        reason=row.get("reason") or "",
    )


def render_markdown(payload: dict) -> str:
    board    = _board(payload)
    summary  = payload.get("summary") or board.get("summary") or {}
    funnel   = payload.get("funnel") or {}
    sgp_legs = payload.get("sgp_legs") or []

    lines = [
        f"SportsEdge {payload.get('sport') or board.get('sport') or 'FOOTBALL'}"
        " — sides, totals, alt lines, props, SGP legs",
        f"run_status={payload.get('run_status') or payload.get('status')}  "
        f"both_sides={summary.get('both_sides')}  "
        f"catalog_complete={summary.get('catalog_complete')}",
        f"sides={summary.get('side_rows')}  "
        f"totals={summary.get('total_rows')}  "
        f"props={summary.get('prop_rows')}  "
        f"sgp_legs={funnel.get('sgp_legs_parsed', len(sgp_legs))}  "
        f"bets={funnel.get('bets_emitted', 0)}  "
        f"sgp_edge+={funnel.get('sgp_edge_positive', 0)}",
        "",
        "Both sides listed. Missing quote = BLOCKED, not omitted.",
        "Alt lines appear in SIDE/TOTAL lane under surface market name.",
        "Complement priced only from supplied opposite quote.",
        "NOT Model_P / NOT Truth Gate / NOT OFFICIAL.",
        "",
        "## SIDES / TOTALS / ALT LINES / PROPS",
        "| lane | market | side | line | odds | model_p | edge | status | reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    board_rows = list(board.get("rows") or [])
    board_rows.sort(key=lambda r: (
        str(r.get("lane") or ""),
        str(r.get("market") or ""),
        float(r.get("line") or 0),
        str(r.get("selection") or r.get("side") or ""),
    ))
    for row in board_rows:
        lines.append(_fmt_board_row(row))
    if not board_rows:
        lines.append("|  |  |  |  |  |  |  |  | no board rows |")

    # ---- SGP legs section ----
    if sgp_legs:
        lines += [
            "",
            "## SGP LEGS (independent prices — correlation NOT modeled)",
            "Each leg priced in isolation. SGP true probability requires",
            "joint simulation. Use as per-leg floor checks only.",
            "",
            "| leg | game | market | side | line | odds | model_p | edge | status |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for leg in sgp_legs:
            mp = leg.get("model_p")
            ed = leg.get("edge")
            lines.append(
                "| {idx} | {game} | {mkt} | {side} | {line} | {odds} | {mp} | {ed} | {st} |".format(
                    idx=leg.get("leg_index", ""),
                    game=leg.get("game_id", ""),
                    mkt=leg.get("market", ""),
                    side=leg.get("side", ""),
                    line="" if leg.get("line") is None else leg["line"],
                    odds="" if leg.get("american_odds") is None else leg["american_odds"],
                    mp="" if mp is None else round(float(mp), 4),
                    ed="" if ed is None else round(float(ed), 4),
                    st=leg.get("bet_status", ""),
                )
            )

    lines += [
        "",
        "Prop engines remain NO_ENGINE until independently validated.",
        "SGP correlation not modeled. Card does not grant staking authority.",
    ]
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
