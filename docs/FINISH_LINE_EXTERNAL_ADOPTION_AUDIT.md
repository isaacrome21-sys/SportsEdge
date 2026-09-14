# SportsEdge finish-line external-adoption audit

Status: RESEARCH_ONLY / NO_AUTHORITY

This file tracks external public implementation patterns that may eliminate a concrete SportsEdge blocker. Nothing listed here grants Model_P, Truth Gate, promotion, staking, OFFICIAL, DFS production-readiness, or untouched-readout authority.

## Adoption rule

Adopt only when all of the following are true:

1. a current SportsEdge blocker is named;
2. the upstream repository/license permits the intended use;
3. the adopted surface is smaller than building a parallel subsystem;
4. the integration preserves SportsEdge PIT/provenance/fail-closed semantics;
5. tests prove the adopted behavior on SportsEdge contracts;
6. model/evidence authority remains governed by SportsEdge, never by the upstream project.

## Candidate lanes

### NFL data + play-by-play: nflverse / nflfastR

Potential use: schedule, play-by-play, player participation/stat feeds, drive/play features, deterministic source manifests.

SportsEdge boundary: raw/derived football data only. No upstream prediction is treated as SportsEdge Model_P. Exact release URL, season/week, fetch timestamp, and content SHA must be preserved.

### MLB event data: pybaseball + MLB StatsAPI/Statcast patterns

Potential use: Statcast pitch/batted-ball retrieval and standardized historical event features needed by the MLB joint path fitter.

SportsEdge boundary: retrieval/feature engineering only. Production use requires PIT timestamp rules and pinned raw-source hashes; current StatsAPI live lineup/probable-pitcher path remains authoritative for same-day availability.

### DFS roster optimization: pydfs-lineup-optimizer patterns

Potential use: exact roster eligibility, salary-cap and team/position constraints, late-swap-style roster legality checks.

SportsEdge boundary: optimization mechanics only. Projection distributions, ownership, field simulation, payout EV, and lineup selection authority remain SportsEdge-owned. Do not replace the current correlation/field-simulation roadmap with a point-projection optimizer.

### CFB play-by-play/data: cfbfastR / CollegeFootballData-compatible patterns

Potential use: possession/play features, schedule/team identity normalization, historical participation where legally and operationally available.

SportsEdge boundary: source completeness must be explicit. No silent fallback from missing player participation/depth data; no backfilled PIT claims.

## Finish-line blockers this audit is intended to close

- NFL: governed V2K data/feature pipeline, attempt-1 freeze, chronological validation, fresh untouched evidence.
- CFB: reproducible player/game feature history and prospective PIT capture without contaminating the frozen candidate process.
- MLB sportsbook: verified historical paired/closing evidence remains a separate hard blocker where free/public sources cannot establish the required semantics.
- MLB DFS: strictly-prior fitted PA/hook/baserunning inputs, complete joint player paths, calibrated ownership, contest-field duplication/payout simulation, and chronological validation.
- Unified DFS: sport-specific automatic projection producers, ownership calibration, field simulation, and payout-EV selection before any production-calibrated claim.

## Explicit non-adoptions

Do not adopt capper picks, market-derived target leakage, opaque prediction APIs, repositories without a compatible license for the intended use, or any implementation that cannot preserve source/time provenance. If a required evidence source is not reachable with the available data, the terminal state is INSUFFICIENT_EVIDENCE rather than endless searching or semantic weakening.
