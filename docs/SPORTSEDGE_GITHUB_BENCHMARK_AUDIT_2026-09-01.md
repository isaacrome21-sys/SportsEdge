# SportsEdge MLB / CFB / NFL GitHub benchmark audit — 2026-09-01

## Scope

This audit compares SportsEdge's current automation-first, fail-closed architecture with mature public sports-data projects. The objective is not to copy external model coefficients or market-derived projections into Model_P. The objective is to adopt stronger acquisition, identity, caching, schema, provenance, speed, and historical-feature practices where they are compatible with SportsEdge governance.

## Benchmarked projects

### nflverse / nflreadr + nflfastR

High-value patterns observed:

- packaged, rapidly accessible season releases instead of re-scraping every historical play on every run;
- configurable memory/filesystem/off caching;
- explicit data dictionaries;
- stable load families for play-by-play, weekly player stats, rosters, depth charts, injuries, snap counts and play-level participation;
- play-level participation includes players on field, box count and offensive formation;
- deep historical play-by-play, drives and series;
- expected-points, win-probability, completion-probability and expected-YAC reference models;
- database update path for durable local historical stores.

SportsEdge gap/opportunity:

- NFL already uses nflverse schedule/depth-chart data, but should expand PIT-safe ingestion to injuries, participation, weekly stats, snap counts and advanced play-by-play rather than leaving those classes missing;
- add a formal provider manifest and schema fingerprints so nflverse schema changes fail closed instead of silently remapping;
- use prebuilt historical releases/cache for repeated Model_P rolling-feature work instead of repeated remote pulls;
- retain external nflfastR model outputs as benchmark/context unless separately validated for Model_P use. Raw objective play-level fields may enter Model_P under PIT rules.

### sportsdataverse / cfbfastR

High-value patterns observed:

- prebuilt full-season loaders;
- classic and ESPN-derived play-by-play with EPA/WPA and participant IDs;
- schedules, rosters, drives, box scores, play participants, advanced statistics and officials;
- weekly ratings and team summaries;
- team talent, recruiting, returning production and ID crosswalks;
- ability to write loaders directly into a database;
- multiple source families shaped to common conventions.

SportsEdge gap/opportunity:

- CFB AUTO currently covers slate discovery, weather and prior-only team efficiency but still lacks objective depth-chart/usage/workload/coaching layers;
- adopt PIT-safe participant, roster, play-by-play and returning-production acquisition where FBS identity can be established;
- add crosswalk registries rather than fuzzy matching across CFBD/ESPN/NCAA identities;
- use officials data for referee-tendency research only after PIT validation and sufficient sample-size shrinkage;
- external FPI/ratings remain benchmark/context unless independently certified; raw objective team/player data can be candidate Model_P inputs.

### jldbc / pybaseball

High-value patterns observed:

- pitch-level Baseball Savant / Statcast access;
- player-specific and arbitrary date-window queries;
- large advanced field surface including pitch type, velocity, spin, movement, zone, launch speed/angle, expected BA/wOBA, fielding alignment and run/win expectancy changes;
- local cache support;
- multiprocessing for large Statcast windows;
- explicit warning that historical Statcast data can be revised;
- documented stale-cache failure mode for future/empty queries.

SportsEdge gap/opportunity:

- MLB should make pitch-level Statcast rolling windows a first-class automated historical feature source rather than relying only on summary feeds;
- raw Statcast snapshots should be hash-bound and dated because past seasons can be revised;
- large historical windows should be cached and acquired in bounded parallel chunks;
- empty current/future results must never be persisted as successful evidence;
- schema fingerprints should detect Baseball Savant column drift before features are constructed.

## Cross-sport findings

### Already stronger in SportsEdge

SportsEdge is materially stronger than most public sports-data packages in governance and betting-specific safety:

- market data is explicitly separated from Model_P;
- PIT/leakage rules and no-vig benchmark contracts are explicit;
- missing data is fail-closed rather than silently imputed;
- manual/hybrid/automatic paths share evidence semantics;
- source hashes and policy hashes are first-class;
- market-specific promotion gates and Truth Gate logic are substantially more rigorous than ordinary open-source sports-data loaders;
- scoped blockers and delta reruns avoid all-or-nothing slate failure.

### Highest-value missing engineering patterns

1. **Provider capability registry.** Every source should declare sport, domain, priority, trust class, TTL, required schema, live/history support and fallback relationships.
2. **Schema drift fingerprints.** Required-column validation plus deterministic schema fingerprint before normalization.
3. **Historical cache discipline.** Content-addressed immutable historical snapshots, with no negative-cache promotion for empty current/future responses.
4. **Parallel acquisition planning.** Independent domains should fan out concurrently while same-domain sources remain ordered primary -> fallback.
5. **Entity crosswalk registries.** Explicit MLBAM / ESPN / GSIS / CFBD / NCAA IDs where available; no fuzzy matching for predictive joins.
6. **Source revision awareness.** Historical data sources that revise past values must bind acquisition timestamp and source hash to training/replay features.
7. **Local durable feature store.** Repeated RUN IT should read rolling historical features from an incrementally updated cache/database rather than refetching whole seasons.
8. **Reference-model benchmark lane.** nflfastR EPA/WP/CP, cfbfastR EPA/WPA, public advanced baseball estimates can be tracked as challengers/benchmarks without leaking into incumbent Model_P.

## Priority implementation order

### P0 — reliability and speed

- provider manifest + deterministic source hierarchy;
- schema required-field checks/fingerprints;
- negative-cache protection;
- concurrent independent-domain fanout;
- incremental local history cache/feature store;
- source-health telemetry with fast fallback instead of long repeated retries.

### P1 — NFL data depth

- nflverse injuries;
- snap counts;
- play-level participation;
- weekly player/team stats;
- advanced play-by-play for pressure/game-script/formation and coaching features;
- official-source override where official injury/inactive evidence is fresher and authoritative.

### P1 — CFB data depth

- FBS-only roster/player identity crosswalks;
- participant/PBP usage extraction;
- returning production and measurable transfer/talent priors;
- quantified coaching tendencies from strictly prior games;
- officials/referee data in a separately validated feature lane;
- opponent-adjusted efficiency challenger.

### P1 — MLB data depth

- pitch-level Statcast rolling windows and player-specific queries;
- velocity/spin/pitch-mix/whiff/chase changes;
- batted-ball quality, expected outcomes, sprint/defense where available;
- bullpen workload/leverage and catcher context;
- immutable raw snapshot hashes to handle historical Statcast revisions.

### P2 — predictive improvement research

- hierarchical/shrunk rolling features instead of naive recent-sample averages;
- explicit regime-change features and change-point alerts for velocity, role, snap share and coaching behavior;
- correlation calibration from historical residuals for joint Monte Carlo;
- benchmark/challenger ensembles only after forward validation demonstrates incremental value;
- latency-aware betting execution metrics: edge decay vs time-to-bet, not only final CLV.

## Non-negotiable governance

- No external betting line, public split, pick, consensus projection, FPI/spread-derived feature or sportsbook probability enters Model_P merely because a public package exposes it.
- External model outputs remain benchmark/context until independently validated under the same temporal and Truth Gate standards.
- Raw objective sports facts may be promoted to Model_P inputs only with PIT timestamps, identity resolution, provenance and forward validation.
- Provider fallback does not weaken trust classification. A context-only fallback cannot silently satisfy a Model_P-objective requirement.
- Faster acquisition cannot trade away freshness or provenance.

## Implementation landed with this audit

The accompanying `sportsedge.provider_resilience` module adds:

- typed provider capability specifications;
- deterministic primary/fallback planning;
- schema required-field validation;
- schema fingerprints;
- provider-manifest hashing;
- Model_P trust checks;
- explicit negative-live-cache protection;
- a planning primitive for concurrent independent-domain acquisition.

These are infrastructure controls only. They do not change Model_P coefficients, simulation math, edge thresholds, Truth Gate eligibility or promotion status.
