#!/usr/bin/env python3
"""Render the NFL phone card: picks/leans with prices and edges, plus retrieved reasons."""
from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import json
import os

from sportsedge.nfl_attempt9_live_forecast import (
    NO_MODEL_HISTORY,
    NO_MODEL_INTEGER,
    NO_MODEL_MARKET,
    NO_MODEL_MONEYLINE,
    NO_MODEL_SPREAD,
    market_eligibility,
)
from sportsedge.nfl_card_game_info import (
    attach_game_info,
    fetch_issue_comments,
    first_card_lines,
    game_info_lines,
    load_history,
    movement_lines,
    snapshot_marker,
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
    "NO_MODEL:RESIDUAL_QUOTES_OR_HISTORY_UNAVAILABLE": "no research price: fresh paired lines, future kickoff and prior history required",
    "NO_MODEL:PAIRED_RESIDUAL_PRICE_UNAVAILABLE": "no research price: both sides and market anchor required",
}


# Specific refusal behind NO_MODEL:RESIDUAL_QUOTES_OR_HISTORY_UNAVAILABLE.
RESIDUAL_ERROR_TEXT = {
    "QUOTE_TIMESTAMP:INVALID": "capture-time line missing (add 'Captured <ISO time with offset>' under the game)",
    "QUOTE_TIMESTAMP:AWARE_REQUIRED": "capture time has no timezone offset",
    "QUOTE_STALE": "lines older than 30 minutes when the card ran",
    "QUOTE_CLOCK_SKEW": "capture time is in the future",
    "ANCHOR_QUOTE_TIME_SKEW": "spread and total captured at different times",
    "KICKOFF:INVALID": "no kickoff time from the independent schedule",
    "KICKOFF_STARTED": "game already kicked off",
    "SCHEDULE_KICKOFF:NO_MATCH": "game not found on the ESPN schedule",
    "SCHEDULE_KICKOFF:AMBIGUOUS": "more than one ESPN schedule match",
    "SCHEDULE_KICKOFF:UNAVAILABLE": "ESPN schedule unavailable",
    "SCHEDULE_KICKOFF:INVALID": "ESPN schedule kickoff unreadable",
    "MARKET_SPREAD_TOTAL_REQUIRED": "both a spread and a total are required",
    "NO_MODEL:INSUFFICIENT_PRIOR_GAMES": "not enough prior games",
}

# No market is validated, so every engine BET/LEAN displays as WATCH.
VALIDATED_PICK_STATUSES: frozenset[str] = frozenset()


def display_status(row: dict) -> str:
    """WATCH unless the row's engine_status is a validated pick status (none exist)."""
    status = str(row.get("engine_status") or "").upper()
    return status if status in VALIDATED_PICK_STATUSES else "WATCH"


def _plain_reason(code: str, detail: object = None) -> str:
    text = NO_MODEL_TEXT.get(str(code), str(code))
    if code == "NO_MODEL:RESIDUAL_QUOTES_OR_HISTORY_UNAVAILABLE" and detail:
        return "no research price: " + RESIDUAL_ERROR_TEXT.get(str(detail), str(detail))
    return text


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
        inj = (ctx.get("game_info") or {}).get("injuries")
        if inj is None:
            out.append("- Injuries/inactives: not checked by this card.")
        else:
            out.append("- Injuries: ESPN injury report above. Final inactives come out ~90 min before kickoff and are not checked.")
    return out


def render(engine: dict, first_card: dict | None = None, observed_at: str | None = None) -> str:
    games = engine.get("games") or []
    title = " · ".join(f"{g.get('away')} @ {g.get('home')}" for g in games[:3])
    if len(games) > 3:
        title += f" +{len(games) - 3} more"
    lines = [f"**NFL card** — {title or 'no games'}", ""]
    if not any(g.get("picks") for g in games) and engine.get("empty_reason"):
        lines += [str(engine["empty_reason"]), ""]
    ranked: list[tuple[float, str]] = []
    unpriced: list[str] = []
    per_game: list[tuple[dict, list[str], list[str]]] = []
    for game in games:
        away, home = str(game.get("away")), str(game.get("home"))
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
            reason = row.get("no_model") if row.get("residual_mode") else (row.get("no_model") or market_eligibility(row.get("market"), row.get("line")))
            if reason:
                unpriced.append(f"- {label}: {_plain_reason(reason, row.get('residual_research_error'))}")
                continue
            chosen = row.get("pick") or row.get("lean")
            choices = list(row.get("residual_research_prices") or [])
            best = chosen or (max(choices, key=lambda x: float(x.get("ev_per_dollar") or 0)) if choices else None)
            if best is None:
                unpriced.append(f"- {label}: {_plain_reason('NO_MODEL:PAIRED_RESIDUAL_PRICE_UNAVAILABLE')}")
                continue
            ev = float(best.get("ev_per_dollar") or 0)
            status = display_status({**row, **best})
            if chosen:
                text = (f"- **{status}** {label}: {best['selection']} {best.get('line', '')} @ {fmt_price(best['price_american'])}"
                        f" · research EV {ev * 100:+.1f}%"
                        f" · edge {float(best.get('edge_probability_points') or 0) * 100:+.1f} pts vs paired no-vig"
                        " (NOT proven, not a bet)")
            else:
                if row.get("lean_block") == "NO_LEAN:THIN_CALIBRATION":
                    why = "model too far from the line; too few past games to price it"
                elif row.get("lean_block") == "NO_LEAN:PROJECTION_DISAGREES":
                    why = "price-only edge; the model total points the other way"
                else:
                    why = "under the research EV/edge floors"
                if ev > 0:
                    captured = row.get("quote_retrieved_at")
                    try:
                        stamp = datetime.fromisoformat(str(captured).replace("Z", "+00:00"))
                        valid_capture = stamp.tzinfo is not None
                    except (ValueError, TypeError):
                        valid_capture = False
                    if not valid_capture:
                        unpriced.append(f"- {label}: positive estimate withheld: offset-aware quote capture time required")
                        continue
                    text = (f"- **POSITIVE EV — PAPER** {label}: {best.get('selection')}"
                            f" @ {fmt_price(best.get('price_american'))}"
                            f" · estimated EV {ev * 100:+.4g}%"
                            f" · Captured: {row.get('quote_retrieved_at') or 'unavailable'}"
                            f" · model warning: {why} (NOT proven, not a bet)")
                else:
                    text = (f"- **{status}** {label}: best side {best.get('selection')} research EV {ev * 100:+.1f}%"
                            f" · no lean ({why})")
            ranked.append((ev, text))
        per_game.append((game, team_totals, props))
    if ranked or unpriced:
        lines.append("Ranked by research EV per $ (all games; WATCH only, not bets):")
        lines += [text for _, text in sorted(ranked, key=lambda x: -x[0])]
        if unpriced:
            lines += ["", "Not priced:"] + unpriced
        lines.append("")
    for game, team_totals, props in per_game:
        away, home = str(game.get("away")), str(game.get("home"))
        lines.append(f"### {away} @ {home}")
        lines += movement_lines(first_card, engine, away, home)
        lines += game_info_lines(game)
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
        lines.append("Residual pricing: market-anchored research priors (0.15, zero intercept), "
                     "frozen joint-score grid, paired POWER_V1 no-vig. "
                     "No historical residual validation or positive forward CLV; track only.")
    if engine.get("residual_research_policy"):
        lines.append("Residual adjustments are research-only: not validated, no picks, no staking.")
    lines.append(both_side_section(engine))
    lines.append(snapshot_marker(engine, observed_at))
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
    first_card = None
    repo, issue = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("ISSUE")
    if repo and issue:
        try:
            first_card = first_card_lines(fetch_issue_comments(repo, issue))
        except Exception:  # noqa: BLE001 - display-only; the card must still post
            first_card = None
    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}
    observed_at = snapshot.get("observed_at") if isinstance(snapshot, dict) else None
    try:
        asof = date.fromisoformat(str(snapshot.get("slate")))
    except (AttributeError, TypeError, ValueError):
        asof = date.today()
    # Game info runs only for a real issue run (ISSUE is set by the workflow, not by tests).
    history = load_history(os.environ.get("NFL_HISTORY_PATH", ".cache/nfl-history/nflverse_games.json"))
    attach_game_info(engine.get("games") or [], history, asof, fetch_espn=bool(issue))
    (out / "card.md").write_text(render(engine, first_card, observed_at), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
