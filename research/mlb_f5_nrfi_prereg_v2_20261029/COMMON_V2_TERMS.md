# MLB F5 / NRFI forward-market prereg v2: common terms (DRAFT)

**Status: DRAFT. NOT FROZEN, NOT IN FORCE.** PAPER / research only, 0u, no staking authority.
- Nothing in this folder changes `config/deployments.json`. F5_* and NRFI/YRFI stay `eligible=false`.
- This folder supersedes nothing. The Oct 13 preregs on `grok/mlb-f5-nrfi-prereg-20261013` (`docs/preregs/*_20261013.md`) stay as history, unedited.
- Every value that cannot be grounded in the repo is marked **OWNER_PIN_REQUIRED**. A freeze is impossible while any such marker remains.

Version labels: `MLB_F5_INNING_EXPOSURE_NB_V2` and `MLB_NRFI_FIRST_INNING_STARTER_V2`. Both v1 labels (Oct 13) are never evaluated.

## T1. Validation law (owner ruling, Oct 27, 2026; verbatim source `research/activation_designs_20261027/README.md`)
- **VERIFIED** means the construction passed its preregistered chronological out-of-sample validation against BOTH:
  - (a) the existing model for its family, and
  - (b) a contemporaneous market baseline.
- The >=50 graded-pick gate is repealed and appears nowhere here.
- Forward clocks keep grading and reporting (CLV first) but do not gate the label.
- PLAY eligibility additionally requires the primary test at **alpha = 0.05/k**, where k = the number of validated families on the verdict date (counted then, not now).
- Under that test, a market leg must also clear at the (1 - 0.05/k) two-sided interval for PLAY. The label VERIFIED uses the 95% interval defined below.

## T2. One look / anti-peeking
- Each version gets exactly ONE evaluation: after the final 2027 MLB regular-season game is Final, on the frozen code SHA.
- No interim reads of either leg. Grading jobs may write rows, but no metric over them is computed or reported before the look.
- A failed look is recorded as FAIL. Any successor is a new version with its own prereg, never a retune.
- 2027 data seen by a failed version is DESIGN data only.
- 2024 and 2025 are burned for F5/first-inning evaluation (#2156 FAIL; the #1577 2025 holdout) and may be used only as training history.
- 2026 regular season was used by #1580 (production parity) and is also training-only.

## T3. Existing-model baseline (law leg a)
The production m30 model, pinned by commit:
- F5: `sportsedge/f5_distribution.py` + `sportsedge/mlb_f5_features.py` via `sportsedge/mlb_phone_f5_pricing.py` (`build_f5_distribution(..., league_prior_strength=30)`, source label `STRICTLY_PRIOR_F5_LINESCORE_LAST30_LEAGUE_PRIOR_M30`).
- NRFI/YRFI: `sportsedge/shared_first_inning_engine.py`, `FIRST_INNING_EMPIRICAL_VERSION = "mlb_first_inning_empirical_jeffreys_m30_v2"`.
- Both were ported in #1596 (`37cb99274`) after #1578 (held-out) and #1581 (2026 production parity, SHIP).
- Baseline pin commit: **OWNER_PIN_REQUIRED**. This is the main SHA at the freeze act. If production changes after the freeze, the pinned SHA, not live main, is the baseline.

## T4. Market baseline (law leg b, mandatory)
- **Capture source / book: OWNER_PIN_REQUIRED.**
  - The only F5/NRFI odds path on main is `scripts/archive_mlb_additional_odds.py` (markets F5_MONEYLINE, F5_RUN_LINE, F5_TOTALS, NRFI, YRFI). It is The Odds API "additional markets" source, keyed to StatsAPI gamePk.
  - It has not been shown that this path produces DraftKings rows on a schedule.
  - The owner must name the book (DraftKings is the program default) and an admitted capture route, with proof of delivery on at least one live slate before freeze.
- **Price used:** the last captured two-sided quote with `snap_ts` strictly before scheduled first pitch (StatsAPI `gameDate`, UTC) is the "close". Rows without a paired two-sided pregame quote are MARKET_MISSING.
- **Closing-snap window** (how old the last pre-first-pitch snap may be): **OWNER_PIN_REQUIRED**.
- **De-vig:**
  - Two-way markets use multiplicative de-vig (`sportsedge/forward_validation/stats.py::devig_pair`, file at `11d168ddd`).
  - Three-way F5 ML de-vig method: **OWNER_PIN_REQUIRED**. Proportional normalization is the natural extension; it is not pinned in the repo.
- **Market metric:** the market probability is the de-vigged close. On each graded row, compare the candidate's log loss with the market's log loss on the same binary/multiclass target. Leg (b) passes only if the 95% date-clustered bootstrap CI of (candidate − market) mean log loss has upper bound < 0.
- **Reported, not gating:** CLV of the candidate's side vs close, and flat-stake ROI at captured prices. Pick rule for those reports: candidate de-vigged edge > 0. The edge threshold for CLV/ROI reporting is **OWNER_PIN_REQUIRED** (the program precedent CBB G-1 shows an unpinned pick rule is a defect).

## T5. Statistics conventions
- **Bootstrap:** date-clustered (matches #1580's frozen rules), 2000 resamples. The v1 game-level bootstrap is replaced so that same-day correlated games are not treated as independent.
- **Seed:** **OWNER_PIN_REQUIRED** (v1 used 20261013 and #1580 used 20261005; a v2 seed should be new and fixed at freeze).
- **Minimum paired rows** for each leg: **OWNER_PIN_REQUIRED**. #1580 used >=1000 eligible games for model parity, but no market-leg minimum for these families exists in the repo. Below the minimum the verdict is INSUFFICIENT_DATA, never PASS.

## T6. Starter binding and the blocked-rate threshold
- Both candidates price only rows with a verified pregame starter binding from `mlb_pregame_starter_adapter`.
  - That module and `sportsedge/sports/mlb/starter_capture.py` live only on `grok/mlb-f5-nrfi-prereg-20261013`, not on main.
  - **Precondition:** that stack must be reconciled to main, pass an exact-head independent review, and have live capture owner-activated before 2027 opening day. Otherwise every row is BLOCKED.
- Each row is BLOCKED if the starter binding is absent or unverified. There is no fallback to the retrospective boxscore starter.
- **Blocked-rate threshold:** if BLOCKED / (all eligible 2027 RS games) > **OWNER_PIN_REQUIRED**, the verdict is **INSUFFICIENT_DATA** regardless of either leg. The blocked share is always reported.
- The baselines are scored on exactly the candidate's non-BLOCKED, market-paired rows (same-row comparison).

## T7. Freeze scaffolding
The freeze act requires all of the following. A merge is not a freeze unless the owner states it is.
1. No OWNER_PIN_REQUIRED marker remains in the spec files.
2. `SPEC_HASHES.txt` lists sha256 of this file, both v2 preregs and the implementation files (candidate code, grader, adapter). The draft entries are in `SPEC_HASHES_DRAFT.txt`; they are recomputed at freeze.
3. A `FREEZE_RECORD.md` names the version labels, baseline pin commit, capture route, seed and first countable slate.
4. An exact-head independent review of the freeze PR.
5. The owner's merge is the recording act.
- **Deadline:** freeze before 2027-03-01, carried from v1 §6. Missing it means the 2027 window is not used, and a successor prereg must name a later window.
