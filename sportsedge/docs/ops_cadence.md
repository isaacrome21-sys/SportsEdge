# SportsEdge Operating Cadence (intended — no jobs scheduled)

Documented Oct 11, 2026. No cron jobs are created by this doc; scheduling is a
separate decision (parent's call). Everything below is research-only,
HYPOTHETICAL paper output, never bets, never staking.

## 1. Daily ranked board ("The Edge Card")
- **Trigger:** Isaac sends DK lines (chat intake, "run it") for the day's slate.
- **Produced by:** the phone runner (`artifacts/run_it_full.py`) → one research
  card per intake.
- **Contains:**
  - Plays, one line each: play + line + price → modeled probability → EV%,
    ranked by EV (modeled probability stated BEFORE any status language).
  - Factor-coverage audit per selection (verified-used vs missing; missing
    critical factor = blocked with reason, never silently priced).
  - Uncertainty flags (quote freshness, heuristic vs verified inputs,
    NOT_PROVEN_VS_CLOSE).
  - Paper-playable edges listed as RESEARCH_CANDIDATE_NOT_VALIDATED /
    RESEARCH_EDGE — research-only, unvalidated until the harness passes them.
  - **A card with zero playable edges is valid output** ("NO EDGES TODAY");
    no padding to hit a target count.
- **Stored:** card JSON (with `plays`/`rendered_card` from `card_format`) kept
  per run for later settlement; per-board priced/watch/blocked-by-cause counts
  feed the playable-share trend.

## 2. Weekly calibration recap
- **Trigger:** weekly (day/time decided with Isaac; runs only when there is at
  least one settled paper record — a zero-settlement week renders a valid
  empty recap, not a gap to fill).
- **Produced by:** `sportsedge/paper_metrics.py` over settled paper records +
  archived closing lines (evaluation side only), cross-checked with the
  backtest harness (`sportsedge/backtest/report.py` conventions).
- **Contains:**
  - Beat-close %: our independent-lane modeled no-vig vs archived closing
    no-vig, per selection; missing closings degrade to MISSING, never invented.
  - CLV edge (pp): mean(closing_no_vig_p − our_model_p) × 100.
  - Month-by-month paper ledger WITH red months shown; every profit figure
    next to its units-risked denominator; flat 1u paper stakes.
  - Calibration table (modeled p bins vs hit rate) from the harness metrics.
  - Every figure labeled HYPOTHETICAL / RESEARCH ONLY.
- **Explicitly not included:** unverifiable unit claims, streak framing,
  black-box "best model" marketing, anything implying staking authority.

## 3. Guardrails that apply to both
- Market-blind pricing stands: market data lives on the evaluation/archival
  side only, never as a pricing feature.
- Nothing is called a verified edge until it passes chronological
  out-of-sample validation in the backtest harness.
- Missing critical input = blocked with the exact reason; degenerate
  probabilities refused; stale quotes → watchlist, never claimed as EV.
