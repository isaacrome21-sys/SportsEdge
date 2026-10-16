# PREREGISTRATION — MLB Batter Props Challenger (Model Fix Lane, family 1)

- **Directive:** Isaac, Oct 14 2026, 9:51 PM CT: "Daily models get
  fix — Failed." **Owner constraints binding this lane:** (1) the
  failed production model stays FROZEN — this document preregisters
  a CHALLENGER, built and measured evaluator-side; no production
  code, registry, or threshold is touched. (2) The M2/M4 market
  verdicts (separate lane) publish before any model change is
  adopted; this lane proposes and measures only. (3) Adoption
  candidacy requires beating BOTH the frozen engine AND the naive
  baselines on chronological out-of-sample data, paired CIs
  entirely < 0.
- **Label of any output:** RESEARCH_EVIDENCE — retrospective
  calibration evaluation. NOT a market verdict (no historical
  paired batter-prop lines exist), NOT validation.
- **Written:** 2026-10-14, before any challenger score was computed
  on the test split declared in §4.

## 1. The measured defect this challenger answers

Phase 2 (`backtest_program_20261014/`, SPEC_BATTER_PROPS, results
`batter_props_results.json`): the production engine
(`mlb_batter_empirical_game_log_v1`, raw empirical frequency over
the ≤30-game pool) is worst or tied-worst on all 13 stats
(2024–2025, n = 63,114). B1 — Jeffreys-smoothed, UNCAPPED
season-to-date rate — beat it on 13/13; the league rate (B2) beat
it on 11/13. Calibration bins show the mechanism: raw short-window
frequencies are over-dispersed with no regression to the mean
(Hits [0.3, 0.4): predicted 0.348 vs observed 0.535; top bin 0.92
vs 0.668). The defect is variance from an unshrunk short window,
not bias. The challenger is therefore B1's form promoted to a full
distribution, plus the league shrinkage B1 lacked.

## 2. Frozen evaluand (exact)

- Engine: `sportsedge/mlb_batter_empirical.py` `price_batter_market`
  at origin/main `2a713380c7d49733577c238a126f487382634040`
  (verified byte-identical to the Phase 2 evaluand at `12999fc22`).
- Pool contract: `MLBBatterPublicSource.prior_games` semantics —
  same-season hitting gameLog, PA ≥ 1, strictly prior dates, most
  recent ≤ 30 games, ≥ 10 games AND ≥ 20 PA or the fixture is
  excluded and counted.
- The frozen arm is scored by driving the production class exactly
  as Phase 2 did (parity §7).

## 3. Challenger construction (every constant fixed here)

For fixture (batter b, date d) and stat s:

- History H = ALL of b's same-season prior games with PA ≥ 1
  (strictly prior dates; NO 30-game cap), n = |H|, per-game stat
  values x_g exactly as the production collector derives them
  (including derived singles and hits_runs_rbis).
- League distribution L_s(d) = the expanding season-to-date
  empirical distribution of stat s over all starting batters'
  prior games (strictly prior dates) — identical construction to
  Phase 2's B2.
- **Predictive PMF: P(v) = ( Σ_g 1[x_g = v] + K · L_s(d)(v) ) /
  (n + K), with K = 25 games-equivalent** (predeclared: roughly one
  month of games, the scale of the window the frozen engine
  trusts; chosen from the design diagnosis, never adjusted after
  test-split contact).
- Binary legs: P(OVER 0.5) = P(v ≥ 1) from this PMF. Count legs:
  CRPS from this PMF. One construction for all 13 stats; no
  per-stat constants.

## 4. Split discipline (declared before any run)

- **Design/diagnosis data:** 2024–2025 (Phase 2). **Test data:**
  the **2026 regular season** — never scored, binned, or inspected
  by Phase 2 (its populations were 2024–2025 only) and not used in
  choosing any constant above. This family's case is therefore
  **SINGLE_SPLIT (2026)**.
- Population transposes Phase 2 §4 to 2026: regular-season games;
  fixture = (batter, game) where the batter started (boxscore
  starting nine — the gamesStarted field is absent from hitting
  gameLogs, per Phase 2's recorded finding, so boxscores are the
  declared method) and the §2 pool contract is satisfiable.
- Exclusions counted with Phase 2's reasons and precedence
  (NOT_A_STARTER → POOL_GAMES_LT_10 → POOL_PA_LT_20). The sealed
  window [2024-07-01, 2024-09-01) does not intersect 2026 and
  same-season pools cannot reach it: declared not applicable.
- Acquisition (transport only, before scoring): StatsAPI
  players?season=2026, hitting gameLogs 2026, schedule chunks —
  served from the program disk cache pattern
  (`~/workspace/tmp/bt_data/`), plus boxscores for every 2026
  population game. If acquisition proves impossible, the family
  degrades to FORWARD_ONLY with this preregistration + the built
  challenger filed, and that outcome is reported, not worked
  around.

## 5. Arms scored (identical fixture set)

1. **FROZEN** — production engine (§2).
2. **CHALLENGER** — §3.
3. **B1** — Phase 2's baseline exactly as implemented in
   `eval_batter_props.py` (the implementing lines are quoted into
   the results file).
4. **B2** — league climatology (§3's L_s(d) as a standalone
   distribution).

## 6. Metrics and gate

- The 13 stats and forms of Phase 2 §5, unchanged: 8 binary stats
  (Brier + log loss on OVER 0.5) and 5 ladder-only stats (CRPS;
  threshold Brier 0.5/1.5 descriptive).
- Paired per-fixture differences with 95% percentile CIs, block
  bootstrap over ISO calendar weeks, 2,000 resamples, **seed
  20261015**.
- **Adoption gate, per stat:** ADOPT-CANDIDATE iff the challenger's
  paired CIs are entirely < 0 against FROZEN **and** B1 **and**
  B2 — for binary stats on both ΔBrier and ΔLogLoss; for
  ladder-only stats on ΔCRPS. Any other outcome: KEEP FROZEN for
  that stat. Stats are verdicted separately; no pooled cross-stat
  verdict exists. Calibration by decile reported descriptively.
- Support misses counted per arm, as Phase 2 did.

## 7. Verification required before scoring

- **Parity:** ≥ 25 sampled (batter, fixture-date) pairs: evaluator
  pool == production `MLBBatterPublicSource.prior_games` pool with
  a cache-backed getter (25/25 required), mirroring Phase 2 §7.
- **Challenger unit checks:** PMF sums to 1 (1e-12) per fixture;
  with K → 0 the challenger reduces to the uncapped empirical
  distribution (checked on samples, not scored); a fixture with
  n = 0 cannot occur (eligibility requires ≥ 10 pool games).
- **Determinism:** fixed seed; a re-run reproduces the results
  file except timestamps.

## 8. What the verdict does and does not do

An ADOPT-CANDIDATE stat is a recommendation to Isaac, nothing
more: adoption is an owner act, sequenced after the M2/M4 market
verdicts publish, and would ship as new production code under its
own review — not as an edit performed by this lane. A KEEP FROZEN
outcome is reported in full, with CI positions, and closes this
challenger; no re-tuning of K (or any constant) on the 2026 split
is permitted — a second challenger would need a new
preregistration and a new untouched split.
