#!/usr/bin/env python3
"""Strict issue intake and research-only phone summary. Zero sportsbook calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

MAX_BODY = 50000
MAX_ROWS = 80
SPORTS = frozenset(("NFL", "CFB", "NBA", "MLB"))
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
        f"Input rows: {int(summary.get('rows', 0))} · Research candidates at estimated EV ≥ {100*float(card.get('min_ev',0.02)):.1f}%: **{len(rows)}**",
        "",
        "**Projection-first research candidates (independent, UNVALIDATED)**",
        "Same-book DK no-vig is a reference, not independent sharp-market confirmation.",
        f"Raw model EV ≥ {100*float(card.get('min_ev',0.02)):.1f}% and straight price ≥ −165: **{len(projections)}**",
        "",
        "| Game | Selection | DK | Model p | DK no-vig p | Edge (pp) | Raw EV |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in projections[:12]:
        estimate = row["independent_projection"]
        lines.append(
            f"| {safe(row['game'])} | **{safe(row['selection'])}** | "
            f"{fmt_price(row['odds_american'])} | {float(estimate['estimate_p'])*100:.1f}% | "
            f"{float(estimate['market_no_vig_p'])*100:.1f}% | "
            f"{float(estimate['edge_vs_dk_no_vig_pp']):+.1f} | "
            f"{fmt_percent(estimate['ev_per_dollar'])} |"
        )
    if not projections:
        lines.append("| — | No qualifying independent research candidates on this board | — | — | — | — | — |")
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
        "**Conservative book-anchored research candidates (15% unfitted residual)**",
        "",
        "| Game | Research selection | DK | Estimate | Estimated EV |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in rows[:12]:
        lines.append(f"| {safe(row.get('game'))} | **{safe(row.get('selection'))}** | "
                     f"{fmt_price(row['odds_american'])} | {fmt_percent(row['estimate_p'])} | "
                     f"{fmt_percent(row['ev_per_dollar'])} |")
    if not rows:
        lines.append("| — | No eligible research candidates at supplied prices | — | — | — |")
    lines += ["", "**Rejected or unpriced:**"]
    excluded = [(k,v) for k,v in sorted(counts.items()) if k != "RESEARCH_EDGE"]
    if excluded:
        lines.extend(f"- {safe(k)}: {int(v)}" for k,v in excluded)
    else:
        lines.append("- No excluded rows")
    for d in (card.get("diagnostics") or [])[:8]:
        lines.append(f"- Row {int(d.get('input_index',0))+1}: {safe(d.get('status'))} · {safe(d.get('reason'),170)}")
    receipts = card.get("source_receipts") or []
    fetched = sum(r.get("status") == "FETCHED_AT_RUNTIME" for r in receipts)
    missing = sum(r.get("status") == "UNAVAILABLE" for r in receipts)
    malformed = [r for r in receipts if r.get("status") == "UNUSABLE_SCHEMA"]
    lines += ["", f"Free context: {fetched} retrieved, {missing} unavailable, "
              f"{len(malformed)} unusable-schema reports. No paid odds calls.",
              "Full model card and source receipts are available in the workflow artifact.",
              f"GitHub Actions run: {safe(run_url, 300)}"]
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
        for row in rows[:8]:
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
            text = render_card(card, run_url=args.run_url,
                               intake_at=(event.get("issue") or {}).get("updated_at") or "")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SystemExit("FREE_RESEARCH_ISSUE_ERROR:" + safe(exc, 160)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")

if __name__ == "__main__":
    main()
