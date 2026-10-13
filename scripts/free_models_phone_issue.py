#!/usr/bin/env python3
"""Strict issue intake and research-only phone summary. Zero sportsbook calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

MAX_BODY = 1000000
MAX_ROWS = 2000
SPORTS = frozenset(("NFL", "CFB", "NBA", "CBB", "MLB"))
TRIGGER = "[FREE RUN IT]"
JSON_FENCE = re.compile(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", re.I | re.S)

class IntakeError(ValueError):
    pass

def parse_issue(event):
    issue = event.get("issue") or {}
    if not str(issue.get("title") or "").upper().startswith(TRIGGER):
        raise IntakeError("TITLE_MUST_BEGIN_FREE_RUN_IT")
    body = issue.get("body")
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY:
        raise IntakeError("ISSUE_BODY_MISSING_OR_TOO_LONG")
    fences = JSON_FENCE.findall(body)
    if len(fences) == 1:
        content = fences[0]
    elif not fences and body.lstrip().startswith(("{", "[")):
        content = body
    else:
        raise IntakeError("REQUIRES_EXACTLY_ONE_JSON_FENCE_OR_PLAIN_JSON")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise IntakeError("JSON_PARSE_FAILED") from exc
    if isinstance(data, list):
        data = {"lines": data}
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        raise IntakeError("LINES_ARRAY_REQUIRED")
    rows = data["lines"]
    if not 1 <= len(rows) <= MAX_ROWS:
        raise IntakeError("LINE_COUNT_OUT_OF_BOUNDS")
    global_sport = data.get("sport")
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise IntakeError(f"ROW_{i}_MUST_BE_OBJECT")
        sport = str(r.get("sport") or global_sport or "").upper()
        if sport not in SPORTS:
            raise IntakeError(f"ROW_{i}_SPORT_REQUIRED")
        if not (r.get("side") or r.get("selection")) or not r.get("market"):
            raise IntakeError(f"ROW_{i}_SIDE_AND_MARKET_REQUIRED")
        if r.get("odds", r.get("price")) is None:
            raise IntakeError(f"ROW_{i}_ODDS_REQUIRED")
    return data

def safe(value, limit=140):
    return re.sub(r"[\r\n\t|<>]", " ", str(value if value is not None else "MISSING"))[:limit].strip()

def fmt_price(x):
    return f"{int(x):+d}" if int(x) > 0 else str(int(x))

def fmt_percent(x):
    return f"{float(x)*100:+.1f}%"

def render_card(card, *, run_url="", intake_at=""):
    if card.get("schema") != "SPORTSEDGE_FREE_RESEARCH_CARD_V1":
        raise IntakeError("INVALID_FREE_RESEARCH_CARD_SCHEMA")
    rows = card.get("edges") or []
    projections = card.get("independent_candidates") or []
    watchlist = card.get("independent_watchlist") or []
    # Lane B is always computed and labeled separately; it is only a research
    # hypothesis until it proves itself out-of-sample.
    anchored_rows = card.get("lane_b_edges") or []
    primary_lane = card.get("primary_lane") or "LANE_A_INDEPENDENT"
    summary = card.get("summary") or {}
    counts = summary.get("status_counts") or {}
    lines = [
        "## SportsEdge FREE RUN IT · research",
        "",
        "**Unvalidated research estimates only — not proven +EV, OFFICIAL, Model_P or staking advice.**",
        "DK prices are user-supplied. Issue timestamps do not verify sportsbook quote freshness.",
        "Model adjustments and the 15% market-anchor weight have not been proven against out-of-sample closes.",
        "",
        f"Run snapshot: {safe(card.get('as_of_utc'))} · Issue last updated: {safe(intake_at)}",
        f"Input rows: {int(summary.get('rows', 0))} · Primary pricing lane: {safe(primary_lane)} · "
        f"Research candidates at estimated EV ≥ {100*float(card.get('min_ev',0.02)):.1f}%: **{len(rows)}**",
        "",
        "**Projection-first research candidates (independent, UNVALIDATED)**",
        "Same-book DK no-vig is a reference, not independent sharp-market confirmation.",
        f"Raw model EV ≥ {100*float(card.get('min_ev',0.02)):.1f}% and straight price ≥ −165: **{len(projections)}**",
        "",
        "| Game | Selection | DK | Model p | Model fair | DK no-vig p | Edge (pp) | Raw EV |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in projections[:12]:
        estimate = row["independent_projection"]
        lines.append(
            f"| {safe(row['game'])} | **{safe(row['selection'])}** | "
            f"{fmt_price(row['odds_american'])} | {float(estimate['estimate_p'])*100:.1f}% | "
            f"{fmt_price(estimate['fair_american']) if estimate.get('fair_american') is not None else '—'} | "
            f"{float(estimate['market_no_vig_p'])*100:.1f}% | "
            f"{float(estimate['edge_vs_dk_no_vig_pp']):+.1f} | "
            f"{fmt_percent(estimate['ev_per_dollar'])} |"
        )
    if not projections:
        lines.append("| — | No qualifying independent research candidates on this board | — | — | — | — | — | — |")
    lines += ["", "**Projection watchlist (not qualifying):**"]
    for row in watchlist[:8]:
        estimate = row["independent_projection"]
        lines.append(
            f"- {safe(row['game'])} · {safe(row['selection'])}: "
            f"model {float(estimate['estimate_p'])*100:.1f}%, raw EV "
            f"{fmt_percent(estimate['ev_per_dollar'])}, "
            f"pair={safe(estimate.get('paired_market_status'),60)}"
        )
    if not watchlist:
        lines.append("- No additional priced model rows")
    lines += [
        "",
        "**Conservative book-anchored research candidates (Lane B, 15% unfitted residual — hypothesis, not validated)**",
        "Lane B shrinks Lane A toward the posted line; it has not proven out-of-sample superiority.",
        "",
        "| Game | Research selection | DK | Lane | Estimate | Estimated EV |",
        "| --- | --- | ---: | --- | ---: | ---: |",
    ]
    for row in anchored_rows[:12]:
        lane_b = (row.get("pricing_lanes") or {}).get("lane_b_anchored") or {}
        lines.append(f"| {safe(row.get('game'))} | **{safe(row.get('selection'))}** | "
                     f"{fmt_price(row['odds_american'])} | {safe(lane_b.get('lane') or 'LANE_B_ANCHORED')} | "
                     f"{fmt_percent(lane_b.get('estimate_p'))} | "
                     f"{fmt_percent(lane_b.get('ev_per_dollar'))} |")
    if not anchored_rows:
        lines.append("| — | No eligible anchored research candidates at supplied prices | — | — | — | — |")
    # The game-only free runner is not the full prop-model card.
    # Keep the visible source/status receipts for each unpriced input.
    prop_picks = card.get("prop_candidates") or []
    prop_watch = card.get("prop_watchlist") or []
    prop_missing = card.get("prop_unpriced") or []
    lines += [
        "",
        "**MLB pitcher + batter history research (free prior games; unvalidated)**",
        f"Current-price research candidates: **{len(prop_picks)}** · "
        f"Stale/price-cap/below-threshold watchlist: **{len(prop_watch)}** · "
        f"No real model or missing data: **{len(prop_missing)}**",
        "Pitcher probable starters and batter starting lineups require separate verification. Unconfirmed batters remain watch-only; no generic league priors.",
        "",
        "| Player / market | DK | Model p | DK no-vig p | Edge pp | Hypothetical EV | Quote |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in (prop_picks + prop_watch)[:24]:
        lines.append(
            f"| {safe(r.get('player_name'))} {safe(r.get('market'))} "
            f"{safe(r.get('selection'))} {safe(r.get('line'))} | "
            f"{fmt_price(r['dk_odds'])} | "
            f"{float(r['model_probability'])*100:.1f}% | "
            f"{float(r['dk_no_vig_p'])*100:.1f}% | "
            f"{float(r['edge_pp']):+.1f} | "
            f"{fmt_percent(r['ev_per_dollar'])} | "
            f"{safe(r.get('quote_status'),50)}"
            f"{' / LINEUP_UNCONFIRMED' if r.get('lineup_status') == 'PUBLIC_BOXSCORE_LINEUP_NOT_VERIFIED' else ''} |"
        )
    if not prop_picks and not prop_watch:
        lines.append("| — | — | — | — | — | — | No player props met verified model/paired quote requirements |")
    for r in prop_missing[:16]:
        lines.append("- No prop model: " + safe(r.get("player_name") or r.get("player_id") or r.get("market")) +
                     " " + safe(r.get("market")) + " " + safe(r.get("selection")) +
                     " — " + safe(r.get("reason"),150))
    if len(prop_missing) > 16:
        lines.append(f"- Plus {len(prop_missing)-16} further unpriced selections in the artifact.")
    lines += ["", "**Rejected or unpriced:**"]
    excluded = [(k,v) for k,v in sorted(counts.items()) if k != "RESEARCH_POSITIVE_EV_UNVALIDATED"]
    if excluded:
        lines.extend(f"- {safe(k)}: {int(v)}" for k,v in excluded)
    else:
        lines.append("- No excluded rows")
    for d in (card.get("diagnostics") or [])[:8]:
        lines.append(f"- Row {int(d.get('input_index',0))+1}: {safe(d.get('status'))} · {safe(d.get('reason'),170)}")
    receipts = card.get("source_receipts") or []
    fetched = sum(r.get("status") == "FETCHED_AT_RUNTIME" for r in receipts)
    public_pitchers = [r for r in receipts
                       if r.get("status") == "PUBLIC_MLB_PRIOR_STARTS_VERIFIED"]
    public_batters = [r for r in receipts
                      if r.get("status") == "PUBLIC_MLB_PRIOR_BATTER_GAMES_VERIFIED"]
    public_football = [r for r in receipts
                       if r.get("status") in {"PUBLIC_NFL_PRIOR_GAMES_VERIFIED",
                                             "PUBLIC_CFB_PRIOR_GAMES_VERIFIED"}]
    missing = sum(r.get("status") == "UNAVAILABLE" for r in receipts)
    malformed = [r for r in receipts if r.get("status") == "UNUSABLE_SCHEMA"]
    lines += ["", f"Free context: {fetched} ESPN/weather retrievals, "
              f"{len(public_pitchers)} verified public MLB pitcher-log inputs, "
              f"{len(public_batters)} verified public MLB batter-log inputs, "
              f"{len(public_football)} verified ESPN football named-stat histories, "
              f"{missing} unavailable, {len(malformed)} unusable-schema reports. "
              "No paid odds calls.",
              "Full model card and source receipts are available in the workflow artifact.",
              f"GitHub Actions run: {safe(run_url, 300)}"]
    for p in public_pitchers[:8]:
        lines.append("- Public MLB pitcher ID " + safe(p.get("pitcher_id"),24) +
                     ": " + safe(p.get("prior_starts"),8) +
                     " prior starts; starter status " +
                     safe(p.get("starter"),60))
    for p in public_batters[:16]:
        lines.append("- Public MLB batter ID " + safe(p.get("batter_id"),24) +
                     ": " + safe(p.get("prior_games"),8) +
                     " prior games / " + safe(p.get("prior_plate_appearances"),8) +
                     " plate appearances; lineup " + safe(p.get("lineup"),80))
    for p in public_football[:20]:
        lines.append("- ESPN football player " + safe(p.get("player_id"),24) +
                     ": " + safe(p.get("prior_games"),8) +
                     " named-stat prior games; fields " +
                     safe(",".join(p.get("stat_fields") or []),100) +
                     "; participation NOT_VERIFIED; research WATCH only")
    for item in malformed[:4]:
        lines.append("- Unusable public injury source for team ID " +
                     safe(item.get("team_id"), 20) + ": " +
                     safe(item.get("reason"), 300))
    factor_report = card.get("factor_coverage")
    if factor_report:
        if factor_report.get("schema") != "SPORTSEDGE_FACTOR_COVERAGE_V1":
            raise IntakeError("UNRECOGNIZED_FACTOR_COVERAGE_SCHEMA")
        by_idx = {r["input_index"]: r["factors"]
                  for r in factor_report.get("by_input_index") or []}
        lines += ["", "**Factor verification — measured vs missing**",
                  "Factor presence does not prove predictive value. Missing factors never mean zero impact."]
        stats = factor_report.get("status_counts") or {}
        lines.append("All input rows (factor-status counts): " +
                     ", ".join(f"{safe(k)}={int(v)}" for k,v in sorted(stats.items())))
        # Report missing factors for blocked and watch rows too. Otherwise
        # a zero-edge card hides the very missingness that caused suppression.
        for row in (card.get("evaluated_rows") or [])[:8]:
            coverage = by_idx.get(row.get("input_index"), {})
            unavailable = [name for name, value in coverage.items()
                           if value.get("status") in ("NOT_WIRED", "MISSING_UNVERIFIED")]
            if unavailable:
                lines.append(f"- {safe(row.get('selection'))}: "
                             f"missing/not modeled: {safe(', '.join(unavailable),240)}")
        lines.append("Statcast, Next Gen, lineup/usage, coaching, refs/umpires and "
                     "travel are not independently priced by this free runner.")
    return "\n".join(lines) + "\n"

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=("parse","render"))
    ap.add_argument("--event-json", required=True, type=Path)
    ap.add_argument("--card", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--run-url", default="")
    args = ap.parse_args(argv)
    try:
        event = json.loads(args.event_json.read_text(encoding="utf-8"))
        if args.mode == "parse":
            text = json.dumps(parse_issue(event), indent=2) + "\n"
        else:
            if args.card is None:
                raise IntakeError("CARD_REQUIRED")
            card = json.loads(args.card.read_text(encoding="utf-8"))
            # The default phone surface uses plain statuses and every input row.
            # render_card remains available only as a legacy diagnostic helper.
            from sportsedge.phone_display import render_phone_card
            text = render_phone_card(card, run_url=args.run_url,
                               intake_at=(event.get("issue") or {}).get("updated_at") or "")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SystemExit("FREE_RESEARCH_ISSUE_ERROR:" + safe(exc, 160)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")

if __name__ == "__main__":
    main()
