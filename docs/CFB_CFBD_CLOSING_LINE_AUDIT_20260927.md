# CFBD historical closing-line source audit — 2026-09-27

Status: source audit only. Market data remains evaluation-only and quarantined from `estimate_p`.

## Current CFBD contract

Current public CFBD v2 exposes `GET /lines` as **historical betting lines and results**, filterable by game/year/week/team/conference/provider:
https://github.com/CFBD/cfb-api-v2/blob/main/src/app/lines/controller.ts

The current response schema explicitly separates current/stored values from opening values:

- `spread` and `spreadOpen`
- `overUnder` and `overUnderOpen`
- `homeMoneyline` and `awayMoneyline`
- `provider`

Source:
https://github.com/CFBD/cfb-api-v2/blob/main/src/app/lines/types.ts

The v2 service reads those values from `gameLines` and joins them to stable CFBD game IDs and line providers:
https://github.com/CFBD/cfb-api-v2/blob/main/src/app/lines/service.ts

Current CFBD data-availability documentation, last verified by CFBD on 2026-09-03, lists **Betting lines and ATS records: 2013–present** and warns that provider/field coverage varies by game:
https://github.com/CFBD/cfb-api-v2/blob/main/docs-site/pages/data-availability.mdx

Current access information points to CFBD's API tier page. As checked 2026-09-27, the free tier advertises 1,000 calls/month and includes historical betting lines:
https://collegefootballdata.com/api-tiers

## Closing-line semantics

The current v2 controller says “historical betting lines and results” but does not itself use the word “closing.” However, the official legacy CFBD API contract for the same `/lines` operation explicitly described it as **“Closing betting lines.”**

Legacy source:
https://github.com/CFBD/cfb-api/blob/master/swagger.yml

Combined with the current schema's separate `*Open` fields, this is strong official-source evidence that `spread`/`overUnder` are intended as the stored closing/final line fields rather than opening fields.

## What is still NOT verified

This does **not** establish per-row capture timestamps, exact close-time timestamps, or complete provider coverage. Current v2 returns no line timestamp field. Therefore SportsEdge must not claim decision-time CLV or row-level PIT capture from CFBD historical lines alone.

The current SportsEdge retrospective archive contract explicitly marks `close_time_certified=false`, `decision_time_certified=false`, and forbids using that research archive for paired no-vig benchmark, CLV, Truth Gate, promotion, staking, or OFFICIAL authority:
https://github.com/isaacrome21-sys/SportsEdge/blob/main/sportsedge/sports/cfb/market_archive_contract.py

## Decision

**Closing-line semantic blocker: materially narrowed, not fully cleared for Truth Gate.**

CFBD is now a viable free candidate for a 2013–present closing-line benchmark, but before promotion evidence:

1. Pull a stratified sample by season/provider and verify values against independently archived pre-kickoff closes.
2. Measure missingness by season, provider, spread/total/ML.
3. Define whether provider-specific close or multi-provider consensus is the benchmark.
4. Create a separate evidence contract for CFBD closes; do not upgrade the existing retrospective archive by inference.
5. Keep all CFBD line data evaluation-only.
