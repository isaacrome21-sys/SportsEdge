# ChatGPT lane: NBA readiness, close comparisons, and MLB foundations — independent source review

**Issue:** #2409; **reviewed main:** `07b46d38334453bac76ceecd017c593452384b5b` (Oct 18).  
**New audit artifact; NOT a frozen-document edit, preregistration, model promotion, or independently scored model verdict.** The original NBA/football research branches and the new Claude records branch are unchanged.

## 1. NBA VERIFIED claims on main

| Claim from `docs/NBA_FEASIBILITY_2026-10-11.md` | What `main` actually demonstrates | Audit classification |
|---|---|---|
| NBA scoreboard event shape/completed-only scores | `sportsedge/sports/nba/espn_verified_source.py` has `NBASource.scoreboard` and `parse_completed_games`; `tests/fixtures/nba/scoreboard_20241023.json` and fixture tests exist | IMPLEMENTED / FIXTURE-TESTED; Oct 11 real-time endpoint claim not independently re-fetched today |
| 30-team ESPN registry | `NBA_TEAMS` and ID/abbreviation/display-name lookup exist; registry fixture and tests exist | IMPLEMENTED / FIXTURE-TESTED |
| Roster `athletes[]` and search results | `roster_player_ids` uses list-form `athletes`; `resolve_athlete` is roster-first, with fallback search verified against fixture roster. Stale search subtitle is documented | IMPLEMENTED / FIXTURE-TESTED; current roster truth requires fresh observation |
| NBA common/v3 gamelog `events` dict, `seasonTypes` categories, stat names | `nba_gamelog_decode.py` and tests match the recorded schema; `nba_public_player_history.py` collects multi-season prior results | IMPLEMENTED / FIXTURE-TESTED; no fresh end-to-end live test performed here |
| Five prior games | `MIN_PRIOR_GAMES = 5` enforced in `nba_public_player_history.py` | CONFIRMED IN CODE; not a prop validation |
| Quarter-summary source and reconciliation | `NBASource.quarter_scores` checks final score against four quarter scores; fixture/test present | IMPLEMENTED / FIXTURE-TESTED; not a market validation |
| Game ML/spread/total engine | `nba_game_market_pricing.py` and research card exist | RESEARCH; `lines_card.VALIDATED_MARKETS = ()` and `W_TOTAL = 0.0` |
| Oct 11 CONDITIONAL_PASS | `docs/NBA_HARNESS_VALIDATION_2026-10-11.md` reports Brier 0.2364 vs naive 0.2473, n=1,306 complementary outcomes / 653 test-game appearances, no market baseline | **REPORT EXISTS, NOT INDEPENDENTLY RE-RUN.** No beat-the-close authority. |

**Important correction to interpretation of the Oct 11 harness:** `scripts/validate_nba_game_markets.py` invokes `walk_forward_splits(min_train=120, test_size=40, embargo_days=1)`, without `step`. In `sportsedge/backtest/splits.py`, `step` defaults to one kickoff block: the ~40-game test windows overlap as the training window grows. Thus **653 reported test-game appearances are not necessarily 653 distinct independent games** and 1,306 side-records are not 1,306 independent observations. Treat published Brier/log-loss as repeated-window descriptive measurements pending unique-game and clustered re-evaluation. No frozen report edited.

## 2. Audit of +0.38 NBA totals gap versus SBR close

**Source now located:** `records/audit-artifacts-20261018` contains:
- `records/audit_artifacts_20261018/NBA_TOTALS_BIAS_DIAGNOSIS_PLAN.md`
- `records/audit_artifacts_20261018/NBA_TOTALS_BIAS_DIAGNOSIS_REPORT.md`
- `records/audit_artifacts_20261018/TESTED_IDEAS_LEDGER.md`

The report claims mean `pred_total - close_total = +0.38` (95% CI +0.21 to +0.55), 7,151 games, using defaults `NBARatingsParams()`, league data through 2021, score-only predictions. It separately reports `pred - actual = -0.09` (CI crosses zero) and concludes `BIAS_UNSTABLE` versus closes. That *is an observed claim in an external lane's report*, not independent corroboration.

**Independent source-level arithmetic performed here:** fetched the original public `flancast90/sportsbookreview-scraper` `data/nba_archive_10Y.json` through GitHub; parsed **13,903** raw rows; independently transcribed the current `ratings_model.py` default online update (k=.05, k_league=.01, k_hca=.002, carry=.6; initial league 100 and home advantage 3), replayed by date/home, used each prediction before its game's result, applied both-teams ≥10 previous games and league ≥200 previous team-games within season 2015–2021 and close within 170–270. This yields **7,753 warmup-qualified games**, **7,172 with valid closing totals**: both counts exactly match the report's sample flow.

The report excludes **21 games** from seven named Finals home-away pairing groups owing to an unmatched hoopR actuals join. Removing the exact seven specified season/home/away groups from the 7,172 source-close subset excludes **21**, and yields **7,151 rows** with year counts **1071, 1048, 1081, 1079, 896, 923, 1053** — identical to the report's seven year counts.

**But the signed gap in this independent replay is +0.392139 points (rounds +0.39), NOT +0.38 at two decimal places.** Year means from this replay are +0.333, +0.248, +0.226, +0.565, +0.928, +0.234, +0.272 (2015–2021); report has +0.33, +0.24, +0.23, +0.56, +0.88, +0.23, +0.27. Largest discrepancy is 2019 (~+0.048 points), where the archive has bubble-date anomalies. The current independent replay does not reproduce the *exact* claimed +0.38, though it corroborates a small positive gap and reproduces the sample size/gates. Critically, the records branch has only the PLAN/REPORT/LEDGER, **not** the report's referenced `scripts/diagnose_nba_totals_bias.py`, `results/nba_totals_bias_scored_games.csv`, joined hoopR actuals or `results/nba_totals_bias_results.json` to compare per-game values, timestamps and hashes.

**Verdict: +0.38 EXACT CLAIM UNREPRODUCED; approximately +0.39 independently reproduced on the same 7,151 source-and-exclusion row count.** Independent bootstrap interval and joined-actuals bias were *not* reproduced. Next step: have the producing lane commit its as-run scorer and 7,151-game row-level audit (or hash-addressed reproducible inputs) to a reviewable records branch, reconcile 2019 date/order and sample identity, then rerun an independent exact-byte comparison. Do not write VERIFIED into a frozen verdict.

## 3. NFL moneyline and spread versus close

Source records are accessible directly on their research branches; these are **reported paired-market results rechecked against the stored results**, not a newly executed 2018–2025 scorer run:

- **Elo v1:** `research/nfl-sides-elo-v1-20261017:research/nfl_sides_elo_v1_20261017/REPORT.md` — MONEYLINE: n=2,219, Elo log loss 0.6363 vs close 0.6089, Δ +0.0274 [+0.0188,+0.0356]; SPREAD: n=2,175, Elo 0.7103 vs close 0.6925, Δ +0.0178 [+0.0092,+0.0259]. Both **DOES_NOT_BEAT_CLOSE**.
- **MOV-Elo challenger:** `research/nfl-sides-challenger-v1-20261018:research/nfl_sides_challenger_v1_20261018/results_nfl_sides_challenger_v1.json` — *same-game subset* n=2,119; candidate log loss 0.637887, Elo v1 0.636794, close 0.608724. The differences from those numbers are +0.029163 candidate-close and +0.001093 candidate-Elo v1, matching stored reported deltas. Stored Δ candidate-close CI [+0.02098,+0.03792]; **DOES_NOT_BEAT_CLOSE**, research SCREEN. No market edge. Note Elo v1 full-set n=2,219 is **not** the paired 2,119 comparison; only the challenger JSON's Elo reference uses the same 2,119 fixtures.

The NFL sides HOLD remains. The challenger results file is not independent proof that price capture had authentic timestamps; archival matchups and scorer need separate independent verification before any qualified beat-the-close label.

## 4. NFL totals LEVEL market leg

- **LEVEL v1** `research/nfl-totals-level-model-20261016:research/nfl_totals_level_model_20261016/REPORT.md`: 1,887 paired games; candidate CRPS 7.7606 vs frozen prior 7.8225, league B2 7.7126; fails both predeclared baseline gates. Explicit **NOT a market verdict**.
- **LEVEL v2** `research/nfl-totals-level-v2-20261017:research/nfl_totals_level_v2_20261017/REPORT.md`: governing Amendment 1 reports CRPS 7.6342, Δ vs frozen −0.1883, vs B2 −0.0785, vs B3 −0.1751 (n=1,887). It is a *screen on reused 2018–2025 development data*, not validation; a later prospective test is required. Explicitly **NOT a market verdict**. Earlier as-run numbers in report body are superseded by Amendment 1.
- **Closing-price comparison for LEVEL:** **MARKET NEVER MEASURED** for v1 or v2 in these records. They used score-only/climatology baselines even when the underlying NFL dataset carried line fields; no retrospective market verdict is implied.

## 5. Baseball HR and H+R+RBI, with Claude

- On **main**, `sportsedge/research/mlb_joint_market_readout.py` already supports research `HOME_RUNS` and `HITS_RUNS_RBIS` marginals from coherent simulated paths, with authority flags all false; `sportsedge/mlb_hr_prop_model.py` also contains a standalone Statcast-oriented research HR estimator with named missing-input refusals. These are **existing research constructors**, not new deployed engines.
- The **first-plate-appearance** PIT pool specifically is **NOT on main**: `sportsedge/research/mlb_first_pa_pool.py` exists only in unmerged draft PR #2346. Main `sportsedge/mlb_plate_appearance_gates.py` continues `PLATE_APPEARANCE_PBP_POOL_UNBUILT` and `PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED` for the three M49 *first-PA betting markets*. **Do not confuse those first-PA selection markets with full-game HR or full-game H+R+RBI, which already have research readout implementations.**
- A stronger *same-path joint HR × H+R+RBI distribution* is in **unmerged draft PR #2345**, `sportsedge/research/mlb_joint_hr_hrr.py`. It is RESEARCH_ONLY/NOT_VALIDATED, not a production market engine, and must be independently audited for conservation (particularly player hits vs pitcher team-hit witness), PIT lineup authenticity and settlement. Do not duplicate or merge without review.
- **Named refusals now:** lack of a genuine strictly-prior PA/PBP pool for first-PA markets; selection-set/settlement unverified; no confirmed current lineup/source cutoff; no market-paired HR/H+R+RBI evaluation; no independent review of draft #2345. **Every numerical output must literally be labeled "research-only, unvalidated estimate".** No independent probability or verified betting edge is claimed by this audit.

## 6. Parked markets

- **CFB:** PR/registration and input/readiness holds mean `UNPRICED; VALIDATED_MARKET_BASELINE_NOT_ESTABLISHED` (no candidate/PLAY output).
- **NHL/UFC/PGA:** parked under #2409. **CBB:** out this week.

**Cross-lane handoff:** This is a repo/source inspection performed in ChatGPT's own lane. Claude or Grok must independently audit this audit's mathematics and any eventual code artifact; no self-approval or merge is proposed.
