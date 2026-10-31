# PREREGISTRATION (DRAFT V2 — NOT FROZEN) — CFB game spread & total: successor validation vs existing model and market

**Status: DRAFT V2 prepared by Rocky, 2026-10-30, revised the same night
under the independent review of V1 (`PREREG_REVIEW.md` in this directory;
verdict READY-WITH-FIXES). NOT FROZEN, NOT IN FORCE.** Freezing is the
owner's act. No game counts toward this test before its freeze. This draft
exists because issue #2961 requires "prospective successor prereg +
independent OOS" for CFB spread and total, and no successor prereg exists.

**Governing contract:** the gate-contract reconciliation ruled by Rocky
under Isaac's delegation (Oct 30, 2026 ~23:20 CT) and recorded verbatim on
issue #2961: the Oct 27, 2026 VERIFIED-GATE REPEAL governs (see §4). This
draft is written against that reconciled contract.

**Revision note:** V2 resolves review fixes F1–F5 in the text and
incorporates F6–F10. Every value pinned by the revision (rather than by V1)
carries a short **PINNED BY REVISION** note at the point of choice, so a
future reviewer can see what changed and why. No threshold, metric, or pass
bar was moved by the revision. The full fix-by-fix map is in
`REVISION_LOG.md`.

**Why a new construction, and why forward:** AM, PM-as-validated, the
converged score-only successor, and the PRIOR_CURRENT_BLEND chrono lineage
have all been screened against the admitted historical closes and failed or
closed (Oct 26 successor screen; Oct 28 status note). Standing law: failed
constructions stay retired, their data is design data, verification accrues
forward only. This prereg therefore (a) binds a NEW construction whose input
space — play-by-play EPA/possession features — none of the failed score-only
constructions used, and (b) validates it on games played AFTER the freeze,
which no construction has seen.

---

## 1. The construction bound

**`CFB_GAME_EPA_JOINT_V1`** (name reserved by this draft; not previously used
by any repo construction):

- **Inputs (only):** play-by-play from the sportsdataverse release assets
  (cfbfastR / sportsdataverse-data form), joined to SDV schedules. Features
  per team, computed from completed games only: offensive/defensive EPA per
  play and per possession, success rate, explosiveness rate, pace
  (plays/possessions per game), each opponent-adjusted by iteration to a
  stated tolerance, plus a points-only margin rating carried as a blend
  component. Preseason prior: prior-season final ratings with shrinkage
  constants stated in the frozen implementation. **No market line, price, or
  closing value of any kind enters the construction.** No injuries/weather/QB
  features (G3: as-of sources do not exist; the backup-QB signal stays
  unevaluated until they do).
- **Outputs:** home and away expected scores → margin and total point
  estimates, and cover/win probabilities from stated margin/total standard
  deviations (constants pinned in the frozen implementation; the production
  PRIORS CFB values SD 19.0/18.5 are NOT inherited silently — the frozen
  implementation names its own).
- **Identity:** at freeze, the implementation file(s), feature constants,
  shrinkage constants, SDs, and this document are hashed; the hash set is the
  test's identity. Any change to the construction after freeze is a new
  version under a new preregistration. The baseline reproduction files are
  part of the same freeze hash set (§2.1).
- **Point-in-time discipline:** for each prediction week, features are
  computed from a snapshot of the PBP/schedule releases committed BEFORE the
  week's first kickoff, using only games completed at least 24 hours before
  each predicted game's kickoff (the repo's established embargo pattern,
  strengthened from a research proxy to committed, hashed snapshots).
  Predictions for every game in the validation sample are written and hashed
  before that game's kickoff. A prediction not committed pre-kickoff does not
  exist for this test.
- **Records location (named):** the weekly snapshot files and the
  pre-kickoff prediction files are committed to the records branch
  **`records/cfb-game-epa-joint-v1`**, one directory per week, each file
  carrying its commit hash as its provenance. §1/§7's commit discipline is
  auditable against that branch and no other location.
  *PINNED BY REVISION (F10): the records location is named here in the text
  (V1 left it implicit) so the commit discipline can be audited; the branch
  name is this draft's choice, following the repo's records-branch pattern.*

## 2. Baselines (both must be beaten; neither is optional)

### 2.1 Existing model

**PM — `CFB_MATCHUP_OFF_DEF_V1` / `CFB_OPPONENT_ADJUSTED_V1`**, reproduced
EXACTLY as in `scripts/evaluate_cfb_sdv_closes.py` (last-5 opponent-adjusted
off/def, 3-game shrinkage toward 28, HFA 2.5, ≥3 prior games/team), run on the
same snapshots and the same games.

- **PM's probability SD convention is pinned:** PM's cover/total
  probabilities are formed with the evaluator's **"prod" SD set — margin SD
  19.0, total SD 18.5** (`SD_MARGIN_PROD` / `SD_TOTAL_PROD` in
  `scripts/evaluate_cfb_sdv_closes.py`, the `PRIORS["CFB"]` values of
  `artifacts/free_models.py`).
  *PINNED BY REVISION (F3): the evaluator emits PM log loss under two SD
  sets — "prod" (19.0/18.5, PM's production identity in `free_models.py`)
  and "lane" (15.5/15.0, from a separate backtest script,
  `backtest_cfb_matchup_blend.py`). V1's "reproduced EXACTLY" did not choose
  between them and the choice materially moves PM's log loss. This text pins
  "prod": the baseline is PM as it actually runs in production, not a
  backtest variant of it. The "lane" set plays no part in this test.*
- **Baseline identity is frozen with the construction:** the baseline
  reproduction itself — `scripts/evaluate_cfb_sdv_closes.py` and the CFB
  branch of `artifacts/free_models.py` — is hashed at freeze into the same
  hash set as §1's implementation files, so the baseline cannot drift
  between freeze and verdict.

### 2.2 Market

The DraftKings closing two-sided price for the same game and market,
captured by the capture lane under the CFB capture-spec section (§5
dependency), de-vigged by **POWER_V1** (the EDGE_FLOOR_DEVIG_V1 policy,
per the Oct 29, 2026 de-vig ruling — named here, before any run, as that
ruling requires).

**Close-validity and missing-close rules (stated in this prereg's own
terms; no external "frozen rule" is incorporated by reference):**

- (a) **The close** for a game is the capture lane's FINAL capture for that
  game under the CFB capture-spec section.
- (b) **A DK close is valid iff** it is two-sided (both sides of the market
  recorded), recorded pre-kickoff, and recorded no more than **60:00 before
  kickoff** (exactly 60:00 is valid). A close failing any leg is missing,
  with exactly one named reason per game/market:
  `NO_CLOSE_ROW` (no FINAL capture exists), `CLOSE_STALE` (recorded more
  than 60:00 before kickoff), `CLOSE_NOT_PREKICKOFF` (recorded at or after
  kickoff), `CLOSE_SINGLE_SIDED` (only one side recorded).
- (c) **Row disposition when a valid DK close is missing (primary metric):**
  the game is **excluded from the primary log-loss comparison in all three
  arms** (construction, PM, market) — the primary metric is computed on
  identical rows across arms, and a row without a de-vigged market
  probability cannot enter any arm. The game remains in the secondary MAE
  readout, flagged **`MARKET_REF_SDV`**, with the SDV published close as the
  reference for the accuracy metrics only; the SDV close carries no prices,
  supports no market probability, and never supports a CLV claim.
  *PINNED BY REVISION (F1): V1 left this row's fate in the primary metric
  undefined (§2.2's SDV fallback vs §4's identical-rows requirement). The
  disposition above is the review's clean reading, adopted verbatim:
  excluded from all three arms of the primary comparison, retained in MAE
  under the flag.*
- (d) **Market-leg sufficiency rule:** if **more than 20%** of the
  validation universe's games at the verdict look lack a valid DK close
  (any reason in (b)), the verdict for that market is
  **`INSUFFICIENT_MARKET_DATA`** and no verdict issues for that market.
  This is a **data-sufficiency rule for the validation itself**, modeled on
  the program's INSUFFICIENT_CLOSE_DATA standard: it certifies that the
  market arm of the comparison rests on enough admissible closes to be the
  comparison the prereg promises. It is **not a VERIFIED gate** — it does
  not reinstate any forward-count or receipts gate struck by the Oct 27,
  2026 repeal (see §4), and a market that fails it has not failed the
  construction; the accrual continues under §3's extension rule and the
  look repeats at the next sample close.
  *PINNED BY REVISION (F1): the sufficiency rule and its label are stated
  here in the text (V1 had no market-leg sufficiency rule), with the
  data-sufficiency characterization the reconciliation requires.*

## 3. Validation sample

- **Universe:** every FBS-involved game (FBS–FBS and FBS–FCS) from the first
  full Saturday after the freeze through the end of that season's **bowl
  games and College Football Playoff games**, extended into the following
  season if the minimum sample (§4) is unmet — the extension rule is stated
  here, in advance, and is the only extension permitted. If the minimum is
  still unmet at that following season's close, **the extension repeats
  season-by-season**, each iteration closing at that season's end (bowl
  games and College Football Playoff games included), until the minimum is
  met; there is no other extension and no early look.
  *PINNED BY REVISION (F7/F9): V1 named neither the Playoff games nor the
  extension's iteration. The universe now expressly includes College
  Football Playoff games (the CFP championship is not a bowl), and the
  extension is stated to repeat season-by-season until the minimum is met.*
  Both teams must satisfy Form 2 identity; the Illinois college-team
  exclusion and the Tennessee owner block apply upstream (an excluded
  fixture is never predicted; if one is, it is a defect, not a row).
- **Chronology:** expanding-window refits only; **refits occur at each
  weekly snapshot commit** — the model that predicts a week's games is the
  fit produced at that week's committed snapshot, from snapshots committed
  before the week's first kickoff, and no other fit predicts any game in
  this test. A game is predicted solely from snapshots committed before its
  kickoff. No random splits anywhere.
  *PINNED BY REVISION (F8): the refit cadence is stated in one line (V1
  said only "expanding-window refits only") so the frozen algorithm's
  identity is complete.*
- **Design data:** 2023–2025 (and all earlier) seasons may be used BEFORE the
  freeze to select features and constants. After the freeze, no design
  decision may be revisited on the basis of validation-sample results.

## 4. Metrics, pass/fail, multiplicity

Per market (SPREAD, TOTAL) separately — never pooled, separate verdicts:

- **Probability formation — all three arms, stated expressly.** For each
  graded game (definition below) and each market:
  - The **construction's** probability of the realized side is formed
    relative to the closing line in the evaluator's Φ form,
    p = Φ((model estimate − closing line) / SD), using the construction's
    own stated SDs (§1): for SPREAD, Φ((model margin − closing margin
    line) / margin SD) for the home-cover event, with the realized side
    read accordingly; for TOTAL, Φ((model total − closing total) / total
    SD) for the over event.
  - **PM's** probability is formed in the same Φ form relative to the same
    closing line, using PM's pinned SDs (§2.1: margin 19.0, total 18.5).
  - The **market arm's** probability is the **POWER_V1 de-vigged closing
    implied probability of the realized side** — the two-sided closing
    price de-vigged by `power_devig` (`sportsedge/devig.py`, method
    `POWER_V1`) and read on the side that actually covered / went over or
    under.
  - The market arm is expressly **NOT** the existing evaluator's ln 2
    placeholder. `scripts/evaluate_cfb_sdv_closes.py` records
    `logloss_market_only = ln 2` because SDV historical closes carry no
    prices; that constant is an artifact of priceless closes. It plays no
    part in this test: every market-arm probability here comes from an
    actual two-sided DK closing price, de-vigged as above.
  *PINNED BY REVISION (F2): V1 defined none of the three arms'
  probabilities in its own text and left the evaluator's ln-2 market arm
  inheritable by silence. All three arms are now defined expressly, and
  the ln-2 placeholder is disclaimed by name.*
- **Primary metric:** mean log loss of each arm's stated probability for the
  realized side (cover / over-under outcome, pushes excluded and reported),
  computed identically for the construction and both baselines on identical
  rows (the rows surviving §2.2(c)).
- **Graded games (definition):** a game is **graded in a market** iff its
  outcome is not a push in that market AND all three arms are present for
  it after §2.2(c)'s disposition — i.e., graded games are exactly the rows
  entering the primary metric for that market. Push rows and
  missing-close rows are excluded from the graded count and reported by
  reason in every readout.
  *PINNED BY REVISION (F7): the 300 minimum in V1 counted an undefined
  "graded games"; the term is now defined as the primary-metric rows.*
- **PASS (per market)** iff BOTH hold at the single verdict look:
  (i) model mean log loss is strictly below PM's AND strictly below the
  market's; and (ii) the game-cluster bootstrap CI for each difference
  (model − baseline) lies entirely below 0 at the adjusted level in
  (Multiplicity). MAE on margin/total is reported as a secondary accuracy
  readout (model vs close vs PM) and calibration (deciles incl. the
  extreme decile, plus calibration slope) is reported, but neither gates
  the verdict.
- **Bootstrap, pinned:** game-cluster bootstrap, **10,000 resamples**,
  **seed 20261028**, two-sided percentile interval at level `1 − α/k`
  (α and k per Multiplicity). A **cluster is one game**: each game
  contributes exactly one row per market to the resample, so the verdict
  computation is reproducible from this text alone.
  *PINNED BY REVISION (F4): resample count, seed, and interval
  construction are stated in the text, following the program precedent —
  CBB Amendment 2's game-cluster bootstrap (10,000 resamples, seed
  20261028, two-sided percentile interval at 1 − α/k). The seed is the
  program's named seed, carried over deliberately so the two families'
  verdict computations share one reproducible convention.*
- **Multiplicity:** confidence level per comparison is `1 − α/k`, α = 0.05,
  where **k = the number of families (across all sports) with an active
  forward clock or an already-validated construction on the verdict date**,
  per the standing multiple-testing policy. **k is recorded at the freeze
  act as well as recomputed at the verdict; the larger figure governs**
  (the CBB Amendment 2 pattern). If k cannot be established at the
  verdict, no verdict issues. The two market verdicts under this prereg
  are two of the families counted in program-wide k at any later verdict,
  and both comparisons within a market (vs model, vs market) are inside
  that market's α share — no additional correction is claimed or hidden.
  *PINNED BY REVISION (F6): V1 recomputed k only at the verdict; the
  freeze-act recording and larger-governs rule are added per the CBB
  Amendment 2 precedent and checklist Q25.*
- **Minimum sample / single look:** no verdict look before **300 graded
  games in that market** (graded as defined above). The verdict look
  happens ONCE, at the first sample close (season end incl. bowls and
  College Football Playoff games, or the §3 extension close) where the
  minimum is met. No interim verdicts, no re-looks; interim readouts, if
  produced, are labeled NON_VERDICT and carry no authority. (This
  minimum is a minimum-sample condition for the single verdict look — it
  counts games in the validation sample, not forward-clock graded picks,
  and is not the repealed ≥50-graded-picks gate; see the contract note
  below.)
- **FAIL** is a result: the construction is retired, never retuned and
  retried under this or a renamed preregistration. A successor is a new
  construction under a new preregistration.
- **CLV treatment:** DK entry/close CLV for the model's selected sides is
  computed and reported under the forward framework's conventions
  (including its missing-close reasons and the >20% INSUFFICIENT_CLOSE_DATA
  trip), as a **reported grade only**. Per the Oct 27, 2026 VERIFIED-GATE
  REPEAL, CLV and forward counts do not gate this verdict; the verdict is
  the chronological OOS validation above.
- **Governing contract — the #2961 reconciliation (cited in place of any
  owner-ruling-pending note).** Issue #2961's gate contract ¶3 was
  reconciled to standing law by ruling of Rocky under Isaac's delegation
  (Oct 30, 2026 ~23:20 CT), recorded verbatim in the comment "Gate-contract
  reconciliation — ruled by delegation" on issue #2961: (1) the
  ≥50-graded-picks gate ¶3 reinstates is **void** (repealed Oct 27);
  VERIFIED = a construction that passed its preregistered chronological
  out-of-sample validation against BOTH the existing model and a
  contemporaneous market baseline; (2) DK receipts and forward clocks do
  **not** gate VERIFIED — they grade; (3) the actual-price-ROI leg is
  unsatisfiable on currently admitted CFB data (no timestamped prices) and
  does not block the spread/total path; actual-price ROI is required only
  where admissible timestamped price data exists. #2961's ordering intent
  stands: independently verify CFB spread, moneyline, and total before
  props. This draft follows the reconciled contract throughout; no term of
  this prereg depends on any further owner ruling on the gate contract.
  *PINNED BY REVISION (F5): V1 carried a stale note that #2961's contract
  "requires an owner ruling." The ruling exists; it is cited here, with
  date and location, so the frozen text carries no open flag.*

## 5. Dependencies that must land before freeze

1. **Capture Spec V1 gains a CFB section**: paired DK entry + close captures
   (moneyline, spread, total; both sides; timestamps; pre-start), per the
   pattern the forward configs cite from CBB. Without it the market baseline
   (§2.2) cannot be DK and §2's fallback governs, which weakens — and must be
   disclosed in — any verdict. A local draft of the section exists
   (`CAPTURE_SPEC_CFB_SECTION_DRAFT.md` in this directory); the actual spec
   edit lands through the capture lane's governed route.
2. **Five-stage receipt discipline proven** over a full Saturday slate
   (the #2961 Kent State P0 failure mode closed). **Reading of this
   dependency, recorded so it cannot be mistaken:** this is a
   **data-provenance condition on this prereg's freeze, not a gate on
   VERIFIED**. This test's market baseline *is* lane-delivered DK closes,
   and the five-stage receipts are how a delivered close is proven
   authentic and pre-start; the discipline therefore stands in front of
   the freeze as delivery discipline. Under the #2961 reconciliation
   (ruling point 2), receipts do not gate the VERIFIED label, and nothing
   in this dependency makes them do so.
   *PINNED BY REVISION (F5): the reading of §5.2 recorded in the
   independent review (§4 of `PREREG_REVIEW.md`) is stated here in the
   prereg text itself.*
3. **The frozen implementation** of §1 committed with its constants and
   snapshot machinery, hash-pinned at freeze together with this document
   and the §2.1 baseline files. The freeze record additionally **enumerates
   the constant values in text** — the construction's SDs, shrinkage
   constants, feature constants, and the opponent-adjustment iteration
   tolerance — so reviewers close on stated values, not on hashes alone.
   *PINNED BY REVISION (F10): the constants-enumeration requirement for
   the freeze record is stated here (V1 deferred all constants to the
   hashed implementation without requiring them legible in the record).*

## 6. Moneyline (explicitly out of scope)

This draft does not cover moneyline. There is no admitted ML price baseline
(zero matched pairs; issue #1070 unresolved) and no pinned ML construction.
Moneyline gets its own preregistration only after #1070 closes or forward DK
ML captures accrue — deriving ML prices from spreads (e.g., published
conversion curves) is a research method, never price evidence. (The
moneyline research plumbing merged Oct 30, 2026 — PRs #2958/#2959/#2960 —
changes nothing here: it preserves and studies candidate pairs; it admits
no timestamped price baseline.)

## 7. Integrity bindings

- Document, implementation, baselines, and inputs are committed before the
  first validation game is predicted; the freeze commit's hashes are the
  test's identity. The hash set comprises: this document; §1's
  implementation file(s) and constants; `scripts/evaluate_cfb_sdv_closes.py`
  and the CFB branch of `artifacts/free_models.py` (§2.1); and the snapshot
  machinery. The freeze record enumerates the constant values per §5.3.
- No retrospective additions, no backfilled predictions or closes.
- Weekly snapshots and pre-kickoff prediction files are committed to the
  records branch named in §1 (`records/cfb-game-epa-joint-v1`); a
  prediction not committed there pre-kickoff does not exist for this test.
- Every readout reports: graded games per market; exclusions by reason
  (pushes, and missing closes by the §2.2(b) reason codes, and
  `MARKET_REF_SDV` rows in the MAE readout); log loss (model, PM, market)
  with the adjusted CIs; MAE table; calibration; CLV summary with
  missing-close breakdown (reported, not gated); and, at the verdict look,
  the §2.2(d) market-leg sufficiency computation.
- PAPER/0u throughout. A PASS creates a VERIFIED construction label for that
  market only; it creates no PLAY, staking, or card authority by itself, and
  no authority transfers between spread and total or to any prop market
  (per #2961's sequencing and standing law).

*Draft V2 prepared Oct 30, 2026 (Rocky), revising V1 under the independent
review in `PREREG_REVIEW.md`. Freeze, amendment, or rejection is the
owner's act.*
