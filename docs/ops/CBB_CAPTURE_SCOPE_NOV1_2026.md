# CBB Nov 1 capture-scope preflight — research-only contract

Status: DRAFT preparation (Oct 27, 2026 CT; live-schedule correction). This document defines research-only market scope. **Critical first-tip gate: Notre Dame @ Villanova plays Sun Nov 1 at 08:30 CST; the existing 09:30 CT precheck is AFTER TIP for that game. A separate pre-tip pass is needed.** It does not connect a browser, admit odds, launch a CBB model, freeze a family, or start a clock. All output is PAPER / 0u.

## Source and identity facts verified for planning

- SportsDataverse release `espn_mens_college_basketball_schedules` contains `mbb_schedule_2027.csv`, `.parquet`, `.rds`; the 2027 parquet asset was updated Oct 18, 2026. Source: https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_mens_college_basketball_schedules
- Its separate `mbb_crosswalk` release has 2026 team and schedule crosswalk assets, but **no 2027 team/schedule crosswalk asset** in the release inventory checked Oct 27. Source: https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/mbb_crosswalk
- **Current ESPN live all-groups feed supersedes the stale September CSV as a discovery input, but is not automatically a certified D1/book slate.** ESPN `dates=20261101&groups=50&limit=500` returns event `401920982` Notre Dame @ Villanova with tip `2026-11-01T14:30Z` = **08:30 CST**, both schools independently confirming Sunday Nov 1 at **09:30 ET**, Rome. Official sources: https://villanova.com/news/2026/4/17/mens-basketball-mens-and-womens-basketball-to-open-2026-27-at-eternal-city-tip-off.aspx and https://und.com/sports/mbball/schedule/ . ESPN IDs: Notre Dame `87`, Villanova `222`. Nov 2 ESPN feed currently has **182** event IDs including non-D1 opponents; Sep 15 CSV yielded only 50 Nov 2 events, 42 with TBD-like 05:00Z tips, and missed the Rome game entirely. An ESPN date bucket is NOT a Chicago-local game day or a verified tip time.
- Independent High Point and Liberty school schedules put their game at **Mon Nov 2 00:00 ET = Sun Nov 1 23:00 CST**, while ESPN event `401920409` shows `2026-11-02T04:59Z`, one minute earlier. Resolve this source discrepancy without silently inferring a precise sportsbook cutoff. Sources: https://highpointpanthers.com/news/2026/4/4/hpu-mens-basketball-game-1-set-for-midnight-in-field-of-68-opening-day-marathon.aspx and https://libertyflames.com/news/2026/4/9/mens-basketball-liberty-to-face-high-point-in-1st-game-of-2026-27-in-field-of-68-showcase .
- A 2026 crosswalk may seed candidate matches but cannot certify 2027 identity. Build and independently check a 2027 ESPN ↔ Torvik ↔ NCAA ↔ DK binding using actual season schedule and institution state before calling the precheck scope-complete.
- Torvik's `bart_archive` documents morning-of-date ratings. A future CBB construction must use an archive date no later than the game's decision date, store the retrieval/hash, and distinguish historical design inputs from prospective capture. Source: https://torvik.sportsdataverse.org/articles/introduction.html

## Capture-scope decision (owner gap-fill Track 0, G6)

Inspect every scheduled D1 men's game for the seven default sections:

1. MONEYLINE — both sides
2. SPREAD — both sides, exact line
3. TOTAL — over and under, exact line
4. TEAM_TOTAL_AWAY — over and under
5. TEAM_TOTAL_HOME — over and under
6. FIRST_HALF_SPREAD — both sides
7. FIRST_HALF_TOTAL — over and under

Inspect the player-props menu regardless of whether props are found. Record ONLY offered categories: points, rebounds, assists, threes, PRA, points+rebounds, points+assists, rebounds+assists. Other encountered markets are `UNMAPPED` and require a separate contract extension, never a guessed alias. An offered section not captured is `MISSING`; a section absent from the rendered DK menu must be explicitly `NOT_OFFERED` with a source-view locator. Do not silently shrink the default census.

## Parser-safe issue grammar

Create an issue with a CBB heading and exactly one final section headed `### CBB_CAPTURE_V1`, immediately followed by a `json` fenced code block. The entire manifest must be inside the fence; duplicate JSON keys, unknown status, malformed timestamps, unlisted categories and missing section reports are rejected. Required payload fields:

- `schema=SPORTSEDGE_CBB_CAPTURE_SCOPE_V1`, `sport=CBB`, `season=2027`, `league=NCAA_MEN_D1`, `source=DRAFTKINGS_RENDERED`.
- Positive decimal-string `espn_event_id` and `dk_event_id`; timezone-aware `scheduled_tip_utc` and `captured_at_utc` strictly before tip and not later than confirmed receipt time.
- Lowercase-hex `raw_sha256` and `raw_locator` are **claims**, not independent proof; #2792's actual append-only source/ingest/archive/card receipts remain mandatory.
- `away` and `home` objects require role, positive ESPN team ID, DK name, `is_college=true`, recognized US state/DC institution code, independently verified 2027 crosswalk status, and a 64-hex crosswalk digest. An Illinois institution (`IL`) is refused regardless of name. Missing/unknown/2026-only identity is refused; pro teams are not college games.
- `sections` must contain exactly the seven default keys. Each section has `status` of `CAPTURED`, `NOT_OFFERED`, or `MISSING` and a nonempty `evidence_locator`.
- `props` requires `menu_examined=true`, a `menu_evidence_locator`, and `offered` / `captured` string arrays (unique, with captured subset of offered).

The new `sportsedge/cbb_capture_scope.py` exposes `parse_cbb_scope_issue(body, received_at_utc=...)` and `validate_cbb_capture_scope(manifest, received_at_utc=...)`. It returns only `SCOPE_RECORDED_RESEARCH_ONLY` or `INCOMPLETE_RESEARCH_ONLY` with named missing sections. Every result hardcodes `delivery_verified=false`, `quote_authenticated=false`, `counted=false`, `official=false`, `staking_authority=false`. It intentionally has no betting/price evaluator.

## Mandatory integration still outstanding before Nov 1

1. Pin actual live 2027 schedule raw bytes with SHA, enumerate Nov 1/2 cross-timezone games and credible tip times (including **Nov 1 08:30 CST Rome** and **Nov 1 23:00 CST Liberty/High Point**), independently reconcile source discrepancies; do not treat September CSV or ESPN date buckets as complete/admitted slate. No synthetic schedule or retroactive additions.
2. Build/independently verify 2027 identity and Illinois-college exclusions. The current public crosswalk release does not itself satisfy this.
3. Wire real CBB rendered-DK per-game capture and issue delivery through #2792's five-stage ledger; enforce due cutoffs and permanent failures. This module only checks syntax/scope.
4. **Before Nov 1 08:30 CST**, execute a separate prospective pregame check for the Rome opener if actually offered on DK; enforce P0 #2792's true pre-tip capture/write window, not just this synthetic parser. Existing **Nov 1 09:30 CST** check stays scheduled for later games; it is NOT a pregame gate for Notre Dame/Villanova. The hourly continuation task is instructed to prioritize a check around **07:26 CST**, but execution/receipt success is not presumed. No historical backfill or counted clock from either check.
5. Keep existing #2660/#2799 data-collector and #2152/#2197 identity PRs independently reviewed/ordered; this document is neither their merger nor a replacement for them.

All sections are research-only until separate preregistration, independent review, freeze and ≥50 forward graded picks with positive CLV and ROI under the standing law.
