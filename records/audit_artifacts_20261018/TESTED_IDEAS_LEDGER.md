# SportsEdge — Tested Ideas Ledger

**What this is:** the single reconciled record of every measured SportsEdge framework in scope — its recorded verdict, its numbers against the model baseline and against the market baseline (shown separately), and its current status. **As of October 19, 2026.** **Rule: a new challenger must be checked against this ledger before it is built — if the construction, or a close variant of it, already has a verdict here, that verdict governs until new evidence on new data says otherwise.**

How to read it: verdict labels are preserved **exactly as recorded** (DOES_NOT_BEAT_*, SCREEN, PASS, etc. — never paraphrased into something stronger). "Model baseline" = the existing model or statistical baseline the test itself used. "Market baseline" = real book/closing prices. Where a test never faced prices, that is stated outright — a calibration result is not a market result. Every figure names its record source. Nothing in this ledger is a validated play; validated families remain **zero**.

---

## 1. Lane A — MLB game-line heuristic engine (former card source)

- **Recorded verdict: DOES_NOT_BEAT_MARKET** (evaluated Oct 13–14, carried into the Oct 17 program matrix).
- **Vs market baseline** (n = 10,237 games, 2021–2025):
  - Moneyline: Brier **0.247856** (Lane A) vs **0.236332** (close); log loss **0.688863** vs **0.663222**.
  - Run line: Brier **0.259303** vs **0.240678**; margin CRPS also worse than climatology.
  - Preserved historical evidence (deficits vs market): ML **+0.0115** / RL **+0.0186** / TOT **+0.0224**.
- **Vs model baseline:** not applicable — Lane A *was* the card model; it survives as the **measured floor** any challenger must first beat.
- **Current status: RETIRED as card-source engine** (owner ruling, Oct 15). It unlocks nothing; the canonical runner still prices game rows via the Lane A heuristic under an unvalidated label.
- **Sources:** `~/MEMORY.md` (Oct 13 Lane A evaluation; Oct 15 rulings); `backtest_program_20261017/MATRIX.md` rows M1, M2.

## 2. Elo C1 and Elo C2 — the Lane A challengers (Oct 14)

**Mapping note (read first):** in the repo's own records, "C1" and "C2" are the two challengers built against Lane A in the Oct 14 challenger program — source: `~/MEMORY.md`, "LANE A CHALLENGERS (Oct 14)", and `backtest_program_20261017/MATRIX.md` row M1 ("Challengers: Elo BEATS_LANE_A_ONLY; Elo→Poisson DOES_NOT_BEAT"). The two NFL Elo constructions that are also sometimes discussed in C1/C2 terms are entered separately under their own recorded names in §3, so nothing is conflated.

### 2a. C1 — Elo (K=5, HFA=25, carryover 0.60), win-probability only

- **Recorded verdict: BEATS_LANE_A_ONLY.**
- **Vs model baseline (Lane A),** n = 10,237: Brier **0.242667** vs Lane A 0.247856; log loss **0.678275** vs 0.688863. C1 became the new measured floor (0.242667).
- **Vs market baseline:** the market still wins — close Brier **0.236332** / log loss **0.663222**, better than C1 on both. The verdict name says it exactly: it beat Lane A **only**.
- **Current status:** research-only challenger record; never a card model, never validated against the market.
- **Sources:** `~/MEMORY.md` (Oct 14 challengers); `backtest_program_20261017/MATRIX.md` row M1.

### 2b. C2 — Elo→run-means (recorded in the matrix as "Elo→Poisson")

- **Recorded verdict: DOES_NOT_BEAT.**
- **Numbers:** no score figures for C2 are in the records opened for this ledger — the record carries the verdict and the closure, not a score line. (Stated plainly rather than reconstructed.)
- **Vs market baseline:** not separately measured — the construction failed before any market claim.
- **Current status: the Elo→runs direction is CLOSED as a moneyline construction.**
- **Sources:** `~/MEMORY.md` (Oct 14 challengers); `backtest_program_20261017/MATRIX.md` row M1.

## 3. The NFL Elo pair (entered under their own recorded names)

**Ruling (Isaac, main chat, Oct 19 ~07:38 CT):** `sportsedge/backtest/elo.py` and `sportsedge/ratings/elo.py` stay separate. If unification is ever wanted, it is its own preregistered change with its own verdict.

### 3a. NFL sides Elo v1

- **Recorded verdict: DOES_NOT_BEAT_CLOSE** — on **both** moneyline and spread (scored 2018–2025 vs nflverse consensus closing lines).
- **Vs market baseline:**
  - Moneyline (n = 2,219): log loss Elo **0.6363** / closing market **0.6089** / naive 0.6907; paired Δ log loss **+0.0274 [+0.0188, +0.0356]**.
  - Spread (n = 2,175): log loss Elo **0.7103** / market **0.6925**; Δ **+0.0178 [+0.0092, +0.0259]**.
  - Descriptive (flat bets where Elo disagreed with the market by >3 points): moneyline ROI **−7.5%**, 67% of those bets on underdogs; spread ROI **−3.6%**, 72% on underdogs — the #2384 signature.
- **Vs model baseline:** Elo v1 is itself the model baseline for §3b.
- **Current status:** research branch only (`research/nfl-sides-elo-v1-20261017` @ `783178d2d`), **not merged**. The #2384 hold on NFL sides stands.
- **Source:** branch record `research/nfl_sides_elo_v1_20261017/REPORT.md` (prereg locked before scoring; result hash reproduced exactly in-lane).

### 3b. NFL sides MOV-Elo challenger v1

- **Recorded verdicts: DOES_NOT_BEAT_CLOSE** and **DOES_NOT_BEAT_ELO_V1** — overall label **SCREEN** (the 2018–2025 closes were already used by §3a; a screen on used data, never a validation).
- **Construction:** MOV Elo (K=20, 538-style MOV multiplier, HFA +48 Elo points, ⅓ inter-season regression); Elo→points and Elo→win-probability calibration fitted on **2010–2017 only**, frozen before scoring.
- **Vs market baseline** (n = 2,119): Δ log loss **+0.02916 [+0.02098, +0.03792]**.
- **Vs model baseline (Elo v1, identical games):** Δ log loss **+0.00109 [−0.00003, +0.00223]** — statistically indistinguishable, point estimate worse.
- **Favorite/underdog diagnostic (recorded):** 749 disagreements >3 points, **570 underdog-backed (76.1%)**; the underdog-backed subset is significantly worse than the close, Δ **+0.07627 [+0.04947, +0.10168]**. Pre-window calibration does **not** cure the underdog-compression signature.
- **Current status:** research branch only (`research/nfl-sides-challenger-v1-20261018` @ `7aa9db08c`; freeze-order copy at `research/nfl-sides-challenger-v1-freeze-order-20261018`), **not merged**. Elo-family ratings have now failed against closes in two constructions (v1 + challenger).
- **Sources:** branch record `research/nfl_sides_challenger_v1_20261018/results_nfl_sides_challenger_v1.json` (read directly for this ledger); `~/MEMORY.md`.

## 4. NFL totals LEVEL model

### 4a. LEVEL v1

- **Recorded verdict: DOES_NOT_BEAT_BASELINE** (preregistered gate required the paired ΔCRPS CI entirely below zero against **both** baselines; both legs failed; paired n = 1,887).
- **Vs baselines (mean total CRPS):** candidate **7.7606**; vs the FROZEN shipped prior (7.8225): Δ **−0.0619 [−0.1497, +0.0235]** — point estimate better, CI crosses zero, leg fails. Vs B2 league total climatology (7.7126): Δ **+0.0479 [−0.0345, +0.1336]** — point estimate *worse* than the league's raw total history, leg fails.
- **Also on record (Stage 2 frame the v1 test reproduced bit-for-bit):** the shipped frozen prior itself vs B2 climatology: Δ **+0.1099 [+0.0283, +0.1987]**.
- **Vs market baseline: NOT MEASURED.** The branch report states it plainly: "NOT a market verdict."
- **Current status:** closed by verdict. Production totals path unchanged (`WATCH_NFL_TOTAL_PRIOR_ONLY`).
- **Source:** branch record `research/nfl_totals_level_model_20261016/REPORT.md` (branch `research/nfl-totals-level-model-20261016`).

### 4b. LEVEL v2

- **Recorded verdict: SCREEN_PASSED** — a historical **screen** on reused 2018–2025 development data. Not out-of-sample validation, not a market verdict, not a promotion input (the report's own labels).
- **Governing numbers (Amendment 1 re-run — the as-run body numbers are superseded on the record by a declared S−2 anchor deviation):** candidate CRPS **7.6342**, n = 1,887; vs FROZEN prior Δ **−0.1883 [−0.2802, −0.1035]**; vs B2 same-season climatology Δ **−0.0785 [−0.1498, −0.0053]**; vs B3 two-season climatology Δ **−0.1751 [−0.2412, −0.1065]**.
- **Vs market baseline: NOT MEASURED.** Every recorded comparison is against climatology baselines. The market/forward leg is **Part B, a prospective test on games from Oct 18, 2026 onward, scored once after the 2026 regular season ends — the scoring run is scheduled Jan 13, 2027.** Until that run exists, there is no market verdict for v2, in either direction.
- **Current status:** SCREEN_PASSED (historical leg only); forward leg pending on the calendar; branch only (`research/nfl-totals-level-v2-20261017` @ `15f5e6a46`, PR #2372), **not merged**, nothing wired.
- **Sources:** branch record `research/nfl_totals_level_v2_20261017/REPORT.md` (Amendment 1 header governs); `backtest_program_20261017/MATRIX.md` row N3.

## 5. Total Hits (MLB, M8/M9)

### 5a. Game Total Hits O/U (M8)

- **Recorded verdict: DOES_NOT_PASS** (frozen harness scoring, Oct 16).
- **Vs baseline:** candidate RPS **2.326372** vs league-constant **2.209232**; Δ **+0.117140 [+0.058118, +0.175806]**, fold 2025, n = 1,118 games. Fold 2024 was **NOT_SCOREABLE_AS_FROZEN**.
- **Vs market baseline: NOT MEASURED** — the scored baseline is a league constant, not a price.
- **Current status: construction CLOSED;** module stays **UNVALIDATED_RESEARCH**. A successor needs a new hypothesis + new preregistration (a draft successor preregistration was filed by the Oct 17 program — NOT_RUN).
- **Sources:** `backtest_program_20261017/MATRIX.md` row M8 (freeze `168009194`, scoring branch `research/total-hits-harness-scoring-20261016` @ `8a8d03e32`); `backtest_program_20261017/REPORT.md` §2.

### 5b. Team Total Hits O/U (M9)

- **Recorded verdict: DOES_NOT_PASS** (same frozen scoring).
- **Vs baseline:** candidate RPS **1.739528** vs league-constant **1.695856**; Δ **+0.043673 [+0.019106, +0.069036]**, fold 2025.
- **Vs market baseline: NOT MEASURED** (same as M8).
- **Current status:** same as M8 — **sequence CLOSED** for both markets.
- **Sources:** `backtest_program_20261017/MATRIX.md` row M9; `backtest_program_20261017/REPORT.md` §2.

## 6. NFL joint-score factory

- **Recorded verdict: NONE EXISTS.** No baseline comparison — against a model baseline or a market baseline — has ever been run for this build. Silence here is not a pass; there is simply no verdict to record, and none is invented for this ledger.
- **What exists:** a built research factory (frozen-artifact profiles → joint score distributions → derivative pricing wrapper), 11 tests, PIT-gated, no market data read anywhere in the path.
- **Calibration blocker (on the record):** in the worked end-to-end example (SEA @ DEN, 2026 Week 7 fixture, 2,000 sims), the simulated **mean total was 15.92 points against a real NFL mean near 46** — play/drive counts are realistic, but the scoring-conversion level runs cold and has never been fitted. The branch report's own words: until the level is fitted and validated, these probabilities are research artifacts and no card should quote them as estimates of real games.
- **Current status: BUILT, research-only, NOT_VALIDATED, production eligibility OFF, NOT merged** (branch `research/nfl-joint-score-factory-20261016` @ `ac964c9ee`). Enabled for explicitly labeled research cards by owner ruling; the factory has no importer in the card path.
- **Source:** branch record `research/nfl_joint_score_factory/REPORT.md`.

## 7. Shrinkage 10/3/1 — research challengers (promotion held)

**What "10/3/1" names:** the 14 measured challengers in the adoption records package — **batter ×10, pitcher ×3, CFB QB ×1** — shrinkage constructions scored against the frozen production engine (FROZEN) and two simple statistical baselines (B1, B2). Source: branch record `research/shrinkage_adoption_records/README.md`.

- **Recorded gate outcome: PASS / ADOPT-CANDIDATE** for the 14 arms — under a preregistered gate requiring paired Δ CIs entirely below zero against FROZEN **and** B1 **and** B2 (batter: ΔBrier/ΔLogLoss for binary stats, ΔCRPS for ladders; pitcher and CFB: ΔCRPS).
- **Vs market baseline: NOT MEASURED — for any of the 14.** The records package states it plainly: *"None of the 14 evaluations was ever scored against market prices,"* and every results file carries the label *"NOT a market verdict, NOT validation, NOT a promotion input."*
- **Recorded numbers (binding leg, Δ vs B2):**
  - Batter arms (form `(counts + 25·league)/(n+25)`, 2026 split, n = 38,511): Hits ΔBrier **−0.0010 [−0.0016, −0.0004]**; Total Bases **−0.0010 [−0.0016, −0.0004]**; Runs **−0.0009 [−0.0015, −0.0003]**; Hits+Runs+RBIs **−0.0010 [−0.0015, −0.0005]**; Singles **−0.0014 [−0.0020, −0.0007]**; Walks **−0.0045 [−0.0051, −0.0040]**; Home Runs ΔCRPS **−0.0010 [−0.0012, −0.0007]**; Extra-Base Hits ΔCRPS **−0.0007 [−0.0012, −0.0003]**; Batter Strikeouts ΔCRPS **−0.0136 [−0.0147, −0.0126]**; Runs+RBIs ΔCRPS **−0.0014 [−0.0024, −0.0003]**.
  - Pitcher arms (form `(counts + 10·league)/(n+10)`, 2026 split, n = 3,382): Outs ΔCRPS **−0.1193 [−0.1350, −0.1035]**; Hits Allowed ΔCRPS **−0.0180 [−0.0278, −0.0079]**; Walks ΔCRPS **−0.0103 [−0.0163, −0.0042]**.
  - CFB QB passing yards (0.25·builder + 0.75·team-chain mixture, 2024, n = 417): ΔCRPS CI **[−0.967, −0.172]**.
- **Reproduction status (Oct 17):** the pitcher-undercard reproduction reproduced **all four verdicts and every gate flag** — OUTS, HITS_ALLOWED, BB = ADOPT-CANDIDATE; ER = KEEP FROZEN — with numbers shifting only in the 3rd–4th decimal (e.g., OUTS challenger CRPS 2.0489 reproduced vs 2.0512 as first recorded; B2 2.1685 vs 2.1705).
- **Current status: RESEARCH CHALLENGERS ONLY. Adoption into production and any promotion are HELD** pending owner certification from identifiable records (owner ruling, Oct 15). The records package sits on a branch as a draft PR (#2368, `research/shrinkage-adoption-records-20261015` @ `6bdc74a06`), gated on recovery of the original pitcher cache, CFB file list, and Collins records. Not production, not validated, not promotable.
- **Sources:** branch records `research/shrinkage_adoption_records/README.md`, `RECORDS.md`, `REPRODUCTION_PITCHER_UNDERCARD_20261017.md`; `~/MEMORY.md` (Oct 15 rulings).

### 7a. The B2 Outs figure — D2 reconciliation (part of the shrinkage record)

- **Resolved:** under the preregistered B2 definition, pitcher B2 (league baseline) Outs CRPS = **2.1705**, reproduced three independent ways.
- The parallel figure **2.0267 is unattributable to any persisted artifact** — no code, no results file, in the workspace or in any git ref; it survives only as a number quoted inside a background completion message and is treated as **withdrawn-by-unverifiability**. It does not contest 2.1705.
- **Source:** branch record `research/shrinkage_adoption_records/D2_RECONCILIATION.md`.

### 7b. EITHER_PITCHER shrunk-marginals repair (M31 — the shrinkage-adjacent measured repair)

- **Recorded verdict: DOES_NOT_BEAT_BASELINE — on all three stats (HA / BB / ER; 2026, 1,396 pairs),** the failing leg being against the league-product baseline in all three. The repair fixes the extreme-rung tail defect (no cell > +2pp) but does not beat the league-average baseline.
- **Vs market baseline: NOT MEASURED** — the comparison is against the league baseline.
- **Verification on record:** independently reproduced (fresh worktrees, full reproduction) — 2024 frozen-arm reproduction max |Δ| = **0.0**, hand check 864 cells PASS, results file hash `d827f294…f464` reproduced exactly; the HA leg is a knife-edge (CI upper **+0.00004**) on the pre-fixed seed. (The Oct 17 program matrix carries the repair as REPORTED_BRANCH, not reproduced by the program; the reproduction above is Rocky's, per MEMORY.md.)
- **Current status: EITHER_PITCHER is CLOSED as research-only.** The family was renamed **EITHER_PITCHER_MARGINAL_TAIL_ERROR** on main (#2362); pricing remains refused.
- **Sources:** `backtest_program_20261017/MATRIX.md` row M31 (branch `research/either-pitcher-shrunk-marginals-prereg-20261017` @ `ec72c2079`); `backtest_program_20261017/REPORT.md` §2; `~/MEMORY.md` (Oct 15 rulings, Oct 17 update).

## 8. MLB pitcher early-exit V1 — component (research-only)

- **Recorded verdict: CASE_CHECK_PASS** — on **n = 2** (Glasnow, Drohan). A case check, **not validation**.
- **Vs model baseline:** no baseline comparison is recorded in the case-check record.
- **Vs market baseline: NOT MEASURED.**
- **Prereg-before-code order: builder-attested, not repo-verifiable.** The case-check record cites a prereg-only commit `6f2217716`; that commit is not in the repo. The primary branch has a single squashed commit `8e2033fd5` above `main`, which contains the prereg, the component, and the case check together. The freeze-order copy's prereg commit `a093907438` is timestamped 2026-10-19 03:51:41Z, after `8e2033fd5` (03:49:18Z). The prereg content hash `d9b276a4…` is unchanged and was not independently verified here.
- **Current status:** research-only; wired into nothing; not merged. Branch `research/mlb-pitcher-early-exit-v1-20261018` @ `8e2033fd5`.
- **Sources:** `docs/MLB_PITCHER_EARLY_EXIT_CASE_CHECK_V1.md`; `docs/MLB_PITCHER_EARLY_EXIT_CORRECTION_NOTE_V1.md` (commit `96a1ecae`, blob `35ad7585`); SportsEdge #2409 comment `6267887116`.

## 9. NBA moneyline — ratings model vs de-vigged market (reproduced; corroboration only)

- **Recorded result:** Brier diff (model − market) **+0.011664 [+0.008653, +0.014651]**, n = 4,374 games, 666 date clusters (2022-23..2025-26; cluster bootstrap, seed 20261017, 2,000 resamples).
- **Reproduction status: reproduced by the session** from preserved artifacts (script, database and model fingerprinted in the record folder). The Oct 19 rerun reproduced the stored figure exactly.
- **Subset:** games where the spread favorite and the moneyline favorite agree (spread = 0 counted as agreeing), 2022-23 through 2025-26. This is a data-quality filter, and it shapes what the 4,374 games mean.
- **Vs model baseline:** not applicable. The figure is the model's win probability (Normal margin, sd fitted 2010-11..2021-22) compared with the market.
- **Vs market baseline:** the market is the de-vigged two-way moneyline from `OddsData.sqlite` (`ML_Home` / `ML_Away`). **Vintage unestablished:** the database has no timestamps, so closing versus opening is unknown. Under the acceptance bar, these are lines of unknown vintage.
- **Verdict:** corroborates a moneyline accuracy gap. It is **not** a beat-the-close verdict. The same script's flat-ROI rows at the quoted moneyline are NO_EDGE on both thresholds (−2.72% at edge ≥ 0.02; −1.53% at edge ≥ 0.04).
- **Current status:** research record only; nothing wired; no card path.
- **Sources:** `records/nba_moneyline_20261019/` on branch `records/nba-moneyline-record-20261019` (`bt_nba_lines.py` b002355d, `common.py` 5c0212e5, `nba_lines_results.json` 808977b0, `FINGERPRINT.md`; database sha256 `4a803d41…`, model sha256 `16e33047…`).

## 10. NBA spread and total — ratings model vs line (accuracy gap; same run as §9)

- **Recorded result (RMSE, points, same 4,374 games as §9):** spread — model **13.83** vs line **13.30**; total — model **21.46** vs line **20.72**. The line is more accurate on both markets.
- **Flat-ROI at the quoted line (date-clustered CI):** spread — −3.5% [−7.3, +0.3] at edge ≥ 2 (n = 2,528), −4.9% [−10.5, +0.3] at ≥ 4 (n = 1,233), −5.7% [−13.6, +1.8] at ≥ 6 (n = 534). Total — −8.1% [−11.5, −4.5] at ≥ 2 (n = 2,946), −8.1% [−12.4, −3.6] at ≥ 4 (n = 1,816), −10.7% [−16.1, −5.6] at ≥ 6 (n = 1,053). All NO_EDGE; the total rows lose with CIs excluding 0.
- **Reproduction status:** same script, database and model as §9; the Oct 19 rerun reproduced the stored file exactly.
- **Vs market baseline:** lines from `OddsData.sqlite`, **vintage unestablished** (no timestamps). Market never measured at the close.
- **Verdict:** **accuracy gap first**, both markets. Not a beat-the-close verdict.
- **Bias diagnosis (added Oct 19, `BIAS_SUMMARY.md` and `bias_nba.py` blob c1663890, same folder):** both gaps are compression toward the middle. Spread: the model is 1.65 points less extreme than the line on favorites [−1.77, −1.54], and short of actual margins by 2.66 on 11+ point favorites; by-season home-margin bias is near zero every season. Total: model − line is +2.72 below a 215 line and −1.89 at 235+. Same shape as the NFL #2384 compression signature.
- **Not covered:** team totals (no team-total column in the database). Open.
- **Current status:** research record only; nothing wired; no card path.
- **Sources:** `records/nba_moneyline_20261019/nba_lines_results.json` (blob 808977b0) on branch `records/nba-moneyline-record-20261019`, keys `rmse`, `spread`, `total`.

## 11. NBA player props — market never measured

- **Markets:** points, rebounds, assists, PRA, other combos, threes, steals, blocks, turnovers, double-double.
- **Recorded verdict: none.** No historical prop prices exist in the repo or the session, so no model has been scored against a price. Each market's status is **market never measured**.
- **Model baseline:** none recorded. No prop model has been scored against a statistical baseline either.
- **Forward-test requirement (per market):** (1) a model frozen and preregistered before the first capture it is scored on; (2) our own timestamped DK captures at entry and close, per Capture Spec V1, with every missed capture recorded and not reconstructed; (3) scoring once the sample reaches the existing `common.py` floor (200 bets, 10 date clusters) or a threshold fixed in that prereg.
- **Capture status (Oct 19):** points, rebounds, assists and PRA are in this week's capture scope. The first board is `dk_line_archive/nba/2026-10-19/1154_ct.json` (manual, owner-directed; Oct 20–21 games), and it has no close capture yet. Other combos, threes, steals, blocks, turnovers and double-double are out of scope this week (#2406), so they have no captures.
- **Current status:** no model, no verdict, no card path.
- **Sources:** #2409 Claude lane item 2; `records/audit_artifacts_20261018/dk_line_archive/INDEX.md` on `records/audit-artifacts-20261018` @ 997cbbd33.

---

## How to check a new idea against this ledger

1. Name the construction precisely (inputs, form, what it predicts) and search this ledger for that construction **and its close variants** — a renamed rerun of a closed construction is still the closed construction.
2. If a verdict exists, it governs: DOES_NOT_BEAT / DOES_NOT_PASS / CLOSED entries can only be reopened as a **new version**, preregistered in advance, scored on data the earlier test did not use — and a calibration-class pass (vs climatology or a league constant) never substitutes for the market leg.
3. If the entry says "market baseline: NOT MEASURED," the honest claim available is calibration only; the market verdict requires timestamped captured prices (forward tests), not another historical rerun.
4. When in doubt, the burden is on the new idea to show what is different — a new information source, a new construction, new data — not on the ledger to re-prove a recorded failure.
