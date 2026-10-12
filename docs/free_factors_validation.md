# Free Factors — Harness Validation Report

**Bar:** each factor must improve chronological out-of-sample Brier **and**
log-loss vs the existing model. Market baseline: **MISSING** in all runs
(no Odds API by Isaac's choice; keys authorized only for Actions-side
archival) → best achievable verdict is **CONDITIONAL_PASS**, never presented
as a validated edge. Prices are never invented.

**Existing model** (all runs): production-equivalent independent projection —
PRIORS base + HFA/2 ± 5-game margin ratings (± form for NFL/CFB); injuries
unavailable historically → 0; weather unavailable historically → 0 except
where noted; **no** market anchoring, **no** market prices. Candidate =
existing + the single factor under test. Lines for SPREAD/TOTAL are the
existing model's fair-line proxy (identical for both models), documented
per run.

**Method:** `scripts/validate_free_factors.py`, run with
`cwd=~/workspace/sportsedge-backtest`. Walk-forward splits, embargo 1 day
(football) / 0 days (MLB daily). Per-factor JSON in
`docs/validation_reports/`.

## Verdicts

| Factor | n (OOS) | Existing Brier → Candidate | Existing LL → Candidate | Verdict | Wired? |
|--------|---------|---------------------------|------------------------|---------|--------|
| key_numbers (NFL push) | 3984 | 0.1166 → 0.1096 | 0.4631 → 0.3855 | **CONDITIONAL_PASS** | YES (labeled) |
| key_numbers (CFB push) | 1460 | 0.0642 → 0.0623 | 0.2786 → 0.2478 | **CONDITIONAL_PASS** | YES (labeled) |
| mlb_park_factors | 74948 | 0.2387 → 0.2423 | 0.6944 → 0.6926 | **FAIL** (Brier not improved; re-validated after fixing derivation bug) | NO |
| component_park (MLB) | — | — | — | NOT_RUN (replaces aggregate; Carty method) | NO |
| platoon_split (MLB) | — | — | — | NOT_RUN (Carty regressed: RHB 2200 PA / LHB 1000 PA) | NO |
| rest (NFL) | 5976 | 0.24673 → 0.24645 | 0.69355 → 0.69341 | **CONDITIONAL_PASS** | YES (rest_margin_adj wired) |
| travel (NFL) | 5976 | 0.24673 → 0.24661 | 0.69355 → 0.69315 | **CONDITIONAL_PASS** | interface defined; venue extraction pending |
| weather_thresholds (MLB) | 11575 | 0.2320 → 0.2321 | 0.7120 → 0.7093 | **FAIL** (Brier not improved vs legacy heuristic; wind leg only — ERA5 archive has no precipitation_probability) | NO |
| weather_interaction (MLB, vs thresholds) | 11575 | 0.2321 → 0.2315 | 0.7093 → 0.6951 | **CONDITIONAL_PASS** (temp/humidity × park improves on the declared thresholds) | NO (stacks on a failed base; see legacy gate) |
| weather_interaction_legacy (MLB, vs legacy) | 11575 | 0.2320 → 0.2312 | 0.7120 → 0.6985 | **CONDITIONAL_PASS** (temp/humidity leg improves on the legacy heuristic; market baseline missing) | YES (labeled: MLB temp/humidity only; xpark leg + NFL leg + thresholds NOT wired) |
| starting_pitcher (ERA) | — | — | — | NOT_RUN | — |
| starting_pitcher (FIP) | — | — | — | NOT_RUN | — |
| bullpen_workload | — | — | — | NOT_RUN | — |
| rotation | — | — | — | NOT_RUN | — |
| team_strength_srs | 3984 | 0.24913 → 0.23254 | 0.69141 → 0.66434 | **CONDITIONAL_PASS** (large) | YES (labeled) |
| time_decay (NFL ratings) | 5976 | 0.24673 → 0.24380 | 0.69355 → 0.68539 | **CONDITIONAL_PASS** | pending |
| venue_hfa | 3984 | 0.2491 → 0.2479 | 0.6914 → 0.6934 | **FAIL** (log-loss not improved) | NO |
| pace (NFL) | 373 | 0.2430 → 0.2488 | 0.6952 → 0.6961 | **FAIL** (both worsened) | NO |
| turnover_regressed (NFL) | — | — | — | NOT_RUN | — |
| nfl_epa | — | — | — | NOT_RUN | — |
| injury_participation | — | — | — | **NOT_VALIDATABLE** (no archived injury feed) + oracle study | declared, fail-closed, HEURISTIC_NOT_VALIDATED |
| mlb_umpire | — | — | — | **NOT_WIRED** (no stable free pregame source) | no |
| backups_depth | — | — | — | **NOT_WIRED** (backup quality not invented) | no |

## Notes per factor

### key_numbers
- NFL push model (PUSH_AT pseudo-market, k ∈ {3,7}, 2024–2025 seasons):
  CONDITIONAL_PASS. Empirical table from 2020–2023 ESPN scoreboards
  (1,116 games; P(|margin|=3)=0.151).
- CFB run errored on a fixture-URL bug (`cfb` vs `college-football` path);
  fixed, rerunning.

### injury_participation
- ESPN's injuries endpoint ignores `?dates=` (verified 2026-10-11: identical
  team/row payloads vs current) → no point-in-time injury feed exists →
  the production rule cannot be scored out-of-sample.
- Oracle ablation (post-game boxscore QB1-out labels, lookahead):
  informational only; sizes the declared -2.5 (NFL) / -3.0 (CFB) coefficient.
- Production: wired as declared, fail-closed, HEURISTIC_NOT_VALIDATED —
  strictly better than the verified-broken QB-blind model (Ravens 1H
  incident), never presented as a validated edge. No double-count with the
  generic injury_points QB component.

### mlb_umpire / backups_depth
- NOT_WIRED by design; reasons in `sportsedge/free_factors.py`.
- 2026-10-11: umpscorecards.com probed (`docs/umpscorecards_probe.md`) — the
  frontend data path is Patreon-gated, no keyless stable API. Plus MLB's 2026
  ABS challenge system structurally shrinks the umpire effect. Documented and
  stopped; no further investment until the harness proves a residual.

### weather (2026-10-11, MySportsWeather calibration)
- Declared wind/precip thresholds (8/12 mph out/in buckets, ±0.25/±0.50 runs)
  FAIL vs the legacy production heuristic on MLB Jun–Aug 2025 totals
  (Brier 0.2320→0.2321, LL 0.7120→0.7093) → NOT wired. Two pre-existing
  script bugs fixed to get here: ERA5 naive-vs-aware datetime crash, and
  ERA5 archive serving all-null `precipitation_probability` (harness now
  validates the wind leg only; production forecast path unaffected).
- Temp/humidity × park interaction (+0.025 runs/°F from 70°F, ×1.25 humid
  heat, ×park factor): CONDITIONAL_PASS vs the declared thresholds
  (Brier 0.2321→0.2315, LL 0.7093→0.6951) — but it stacks on a failed base,
  so the production-relevant gate is `weather_interaction_legacy`
  (legacy + interaction vs legacy).
- Calibration decisions from their published reads: football stays wind-only
  (no cold coefficient — "cold overrated"); no Wrigley-specific wind
  multiplier invented (park-factor scaling is the declared approximation).
- Limits: Jun–Aug window barely exercises sub-70°F; park multiplier
  fail-closed off for 2025 (table is 2022–2024); NFL wind × pass-rate
  interaction still NOT_RUN.

## Guardrail compliance
- Market-blind: no odds used as features in any run. Baseline slot MISSING.
- NHL/Soccer: out of scope, untouched. NBA factors queued for Phase 5.
- Motivation/coaching/news: NOT_WIRED. EPA via nflverse: free GitHub CSVs,
  no key, no Isaac infra.
