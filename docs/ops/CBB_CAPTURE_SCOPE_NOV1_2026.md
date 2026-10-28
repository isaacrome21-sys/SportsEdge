# CBB Nov 1 capture-scope preflight — research-only contract

Status: DRAFT preparation (Oct 27, 2026 CT). This document makes the Nov 1, 09:30 CT capture pre-check's requested market census explicit. It does not connect a browser, admit odds, launch a CBB model, freeze a family, or start a clock. All output is PAPER / 0u.

## Source and identity facts verified for planning

- SportsDataverse release `espn_mens_college_basketball_schedules` contains `mbb_schedule_2027.csv`, `.parquet`, `.rds`; the 2027 parquet asset was updated Oct 18, 2026. Source: https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_mens_college_basketball_schedules
- Its separate `mbb_crosswalk` release has 2026 team and schedule crosswalk assets, but **no 2027 team/schedule crosswalk asset** in the release inventory checked Oct 27. Source: https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/mbb_crosswalk
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

1. Pin actual 2027 schedule raw bytes with SHA and enumerate the Nov 1 slate (no synthetic schedule or retroactive additions).
2. Build/independently verify 2027 identity and Illinois-college exclusions. The current public crosswalk release does not itself satisfy this.
3. Wire real CBB rendered-DK per-game capture and issue delivery through #2792's five-stage ledger; enforce due cutoffs and permanent failures. This module only checks syntax/scope.
4. Execute the Nov 1, 09:30 CT precheck on actual offered games and compare expected vs captured market categories. No historical backfill or counted clock from this precheck.
5. Keep existing #2660/#2799 data-collector and #2152/#2197 identity PRs independently reviewed/ordered; this document is neither their merger nor a replacement for them.

All sections are research-only until separate preregistration, independent review, freeze and ≥50 forward graded picks with positive CLV and ROI under the standing law.
