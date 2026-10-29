# PREREGISTRATION (DRAFT) — UFC moneyline, low-experience segment: full professional-record rating vs the closing market

**Status: DRAFT — NOT FROZEN — NOT ADOPTED.** Counted rows: **0**. No
bout counts toward this test before the owner's freeze act, and no clock
runs under this draft. Nothing in this document builds an engine, runs a
screen, validates anything, or creates a PLAY. Freezing is the owner's
separate act. PAPER / research only.

Family: `UFC / MONEYLINE_H2H` (the only market
`config/ufc_market_surface.json` lists as engine-supported; every other
UFC market remains `unsupported_without_new_engine` and is out of scope
here, as is DWCS — a separate family under its own design note).

Construction: `UFC_ML_LOWEXP_PRORECORD_V1` — first and only version under
this name; any change after a freeze is a new version, judged on data
after the change.

**Lineage.** This draft formalizes the single restricted successor
proposed by the design exploration of Oct 28, 2026
(`research/ufc_successor_design_20261028/DESIGN_EXPLORATION_UFC_ML_SUCCESSOR.md`,
DRAFT PR #2923), as independently reviewed the same day (verdict
**SOUND-WITH-FLAGS**; the review record is pinned in `SPEC_HASHES.txt`).
The review's six flags are discharged in this draft: F-1 at §11.1, F-2
at §11.2, F-3 at §6, F-4 at §5 (with its identity items at §2 and its
window item at §6), F-5 at §7.1, F-6 at §9. Values adopted from program
sources are cited to them; values this draft itself fixes are marked
*fixed by this draft*.

**Predecessor.** `UFC_ML_PIT_RATING_V1` — FAILED_SCREEN, PR #2876,
merged Oct 28, 2026 — remains **RETIRED**. This draft does not
resurrect, amend, re-tune, or re-judge it. Its 2023–2025 holdout is
design data only here: it informed V1 and the diagnosis behind this
construction, and it may never judge this construction. The
unrestricted moneyline remains closed **NO_CONSTRUCTION** on the
exploration's record.

Freeze-coverage: the paths added by this package were tested against
`config/freeze_reconciliation_registry_v1.json` with the repo matcher
(`scripts/reconcile_freeze_deltas.py`) — **NOT GOVERNED**. No config,
registry, workflow, or engine path is touched by this package.

---

## 1. Relationship to existing records

- The V1 design + preregistration draft (Oct 27, 2026) and the V1 screen
  record (Oct 28, 2026) govern V1's test. They are cited here as
  evidence and are not amended.
- `config/ufc_promotion_contract_v1.json` fixes the program's UFC
  promotion gates for the unrestricted family. This draft adopts its
  calibration-error and market-delta values for the segment test and
  adapts its count gates at segment scale (§9 carries the required
  statement of that adaptation).
- Method / rounds / distance / round-of-victory families: untouched by
  this draft; each still needs its own engine work and contract.

## 2. Claim, universe, and identity rules

**Claim (narrow, falsifiable).** In bouts where at least one fighter
has ≤ 2 prior UFC bouts, a rating built on **full professional
records** — every sanctioned pro bout, regional and UFC, rebuilt
point-in-time — differentiates fighters that a UFC-only record renders
identical, and can beat the closing market **in that segment**. The
construction prices nothing outside the segment; abstention is part of
the construction, not a post-hoc filter. It makes no claim about the
unrestricted moneyline, which stays closed.

**Universe.** A bout is in-universe iff either fighter has ≤ 2
completed UFC bouts strictly before the bout's date. Design basis:
V1's debut-any slice was 17.9% of its test window and is the only
low-experience slice V1 measured; the ≤ 2 threshold is an extrapolation
from it — a design choice, **not** a measured optimum, and not tunable
on judged data (§11.1 states the limitation this selection carries).

**Bout-count identity rules** (review flag F-4f):

- A *completed UFC bout* is a bout present in the pinned UFCStats
  per-fight record with outcome win/loss or draw. **No-contests do not
  count** toward a fighter's prior-UFC-bout total (mirroring V1's
  structural exclusion of no-contests from scored rows). **Draws do
  count** toward the total — the bout was completed — but are excluded
  from scored judged rows (§5).
- **Road to UFC** and **The Ultimate Fighter** tournament bouts that
  appear in the per-fight record **count** as completed UFC bouts: they
  are part of V1's population and of the record itself. **DWCS bouts do
  not count** as UFC bouts — they are not in the per-fight record and
  DWCS is a separate family. A fighter's DWCS *appearances* are
  sanctioned pro bouts and count inside their pro-record features (§4),
  per the exploration's DWCS reading, confirmed here.
- "Strictly before" is **date-granular**: bouts sharing a date are
  invisible to one another for counts, features, and ratings (§5
  sequence rule).
- *Fighter identity within the per-fight record* is the record's own
  fighter identity. *Cross-source identity* (per-fight record ↔
  pro-record source ↔ BestFightOdds) requires **both**: (i) equal
  accent-folded normalized names — NFKD normalization with accents
  folded, exactly the `join_key_norm` rule of the V1 screen runner —
  **and** (ii) at least one corroborator: equal date of birth where
  both sources record one, or ≥ 1 shared dated UFC bout (same date,
  same opponent) present in both sources' records for that name.
- A normalized name that maps to more than one distinct fighter in any
  source is a **collision**. Every bout touching a colliding identity
  is excluded from judged scoring and from both baselines on that bout,
  enumerated by name in the audit/screen record, and counted separately
  as `COLLISION_EXCLUDED`. Collisions are enumerated in the §7.1 audit
  for the design windows and re-enumerated for the judged window before
  the screen run, under the §11.2 no-peek rule (identity work uses
  names, dates, and records only — never judged-window outcomes).

## 3. Inputs — verified contents, tiered

| Input | Source | Role in this test | State |
|---|---|---|---|
| UFC per-fight record (event details, fight results, fight stats, fighter tale-of-the-tape) | `Greco1899/scrape_ufc_stats` @ `5d6622ff…`, hash-pinned in `research/ufc_moneyline_screen_20261028/PINS.json`, re-pinned in `SPEC_HASHES.txt` beside this draft | UFC bout history; §2 universe counts; UFC-segment features; design-window outcomes | Pinned for V1's screen and reused under the same pins. The repo stores hashes, not data; workspace copies re-verified 5/5 against PINS.json on Oct 28, 2026. Any run re-verifies hashes before use and re-pulls from the pinned commit on mismatch |
| Recorded prices | Kaggle `mdabbert/ultimate-ufc-dataset` via the author's mirror @ `31d29415…`, pinned in PINS.json | **Design data only** — V1's baseline and the diagnosis source. **Not a judged baseline for any leg of this preregistration** (see the note below) | Pinned; labeled `RECORDED_PRICE_NOT_DK_CLOSE` wherever a design figure is quoted |
| Full professional records (regional + UFC) | One primary source of the Tapology/Sherdog class, **named by the §7.1 admission act**; the other source of that class serves as the audit's independent dated check | The construction's only new information class — the pro-record features of §4 | **NOT ADMITTED.** No feature may be computed from it before the §7.1 audit passes |
| Closing-odds archive | BestFightOdds, via `ufcscraper`-class tooling | Leg A market baseline (A) | **NOT ADMITTED** — gated by §7.2. If admitted, every figure it produces is labeled `ARCHIVE_CONSENSUS_CLOSE_NOT_DK` |
| Forward DK closes | Standing lines lane `[UFC LINES]` captures | Leg B market baseline | Grammar exists; **zero UFC captures banked** as of this draft (lane registry read Oct 28, 2026: 61 entries, none UFC). Gates Leg B (§7.3) |

**Baseline discipline (from the exploration's E3).** No leg of this
test may be judged against the mdabbert recorded price: its book and
its opener/close status are undocumented, and adopting it after the
fact would soften the bar. Legs are judged against an admitted
documented close (Leg A) or genuine forward DK closes (Leg B), or they
do not run.

## 4. The construction (frozen at freeze; any change = new version)

One row per bout. Side A is the first-listed fighter in the per-fight
record's row order for bouts the record carries (the history builder's
`TrainingRow` convention); for Leg B forward bouts the record does not
yet carry, side A is the first-listed fighter in the official bout
order as captured. Target y = 1 iff side A wins. Every feature is
computed from bouts dated strictly before the bout's date (§5 sequence
rule). Odds never enter the feature vector — program law.

### 4.1 Feature vector (exact; the build's artifact fixes this order)

**Pro-record block** (per-fighter quantities, entered differenced
A − B unless noted), from the admitted pro-record source joined to the
per-fight record under §2's identity rules:

- P1 `pro_elo_diff` — pro-record Elo (§5).
- P2 `pro_bouts_diff` — completed pro bouts (win/loss/draw; no-contests
  excluded from the count, by the §2 rule applied to the pro record).
- P3 `pro_years_since_debut_diff` — (bout date − pro debut date) in
  days / 365.25.
- P4 `pro_bouts_trailing_730d_diff` — completed pro bouts with date in
  [bout date − 730 days, bout date). (*Fixed by this draft:* the
  trailing-24-months window is operationalized as 730 days.)
- P5 `pro_win_rate_diff` — pro wins / completed pro bouts (draws in the
  denominator only).
- P6 `pro_finish_rate_diff` — pro finish wins / pro wins; 0.0 when the
  fighter has no pro wins.
- P7 `pro_win_rate_last5_diff` — as P5 over the fighter's last 5
  completed pro bouts (all of them if fewer than 5).
- P8 `pro_finish_rate_last5_diff` — finish wins / wins within those
  last 5; 0.0 when there are no wins in them.
- P9 `pro_opp_elo_mean_diff` — mean of opponents' pre-bout pro-Elo over
  the fighter's prior pro bouts (the engine's
  `opponent_pre_fight_elos` convention, applied to the pro sequence).
- P10 `pro_major_promo_share_diff` — share of completed pro bouts
  fought in the named major-promotion set {Bellator, Cage Warriors,
  DWCS, Invicta FC, LFA, ONE Championship, PFL, RIZIN} (the
  exploration's candidate set, frozen here; promotion identity as
  recorded by the admitted source; unrecognized promotions count as
  outside the set).
- P11 `pro_rest_days_diff` — days since the fighter's last completed
  pro bout (layoff measured on the pro record).
- P12 `no_pro_record_a`, `no_pro_record_b` — side indicators, **not**
  differenced: 1 iff that fighter's pro record was not found in the
  admitted source (§4.3).

**UFC-segment block** — the engine's frozen feature vector
`sportsedge/ufc_training.FEATURES` (17 differenced features:
`elo_diff`, `age_diff`, `reach_diff`, `height_diff`, `slpm_diff`,
`sapm_diff`, `str_acc_diff`, `str_def_diff`, `td_avg_diff`,
`td_acc_diff`, `td_def_diff`, `sub_avg_diff`, `recent_win_rate_diff`,
`sos_diff`, `rest_days_diff`, `late_replacement_diff`,
`experience_diff`), computed by the history builder's snapshot rules
from each fighter's UFC bouts to date — **plus** the four field groups
the V1 design specified and V1's vector omitted (exploration finding
F2), all differenced:

- U1 `kd_per_15_diff` — knockdowns per 15 (snapshot
  `knockdowns_per_15`).
- U2 `control_sec_per_15_diff` — control seconds per 15 (snapshot
  `control_seconds_per_15`).
- U3 `finish_win_rate_diff` — snapshot `finish_win_rate`.
- U4 `finish_loss_rate_diff` — snapshot `finish_loss_rate`.

And one indicator (not differenced):

- U5 `stance_matchup` — 1 iff exactly one fighter is recorded southpaw
  and the other orthodox; 0 otherwise, including when either stance is
  unrecorded. (*Fixed by this draft* as the operationalization of the
  V1 design's stance-matchup indicator.)

`late_replacement_diff` is carried as part of FEATURES and is expected
to be structurally zero in every historical window (no booking-change
source exists); it is not dropped, so the UFC-segment block is exactly
FEATURES + F2.

### 4.2 Learner

Plain logistic regression on the §4.1 features + Platt calibration on
the calibration window only — deliberately V1's philosophy: the claim
under test is that the *new information class* carries edge, not that
a flexible learner can find some. Implementation adopted by reference
from the engine: `sportsedge/ufc_training.fit_logistic` (full-batch
gradient descent; epochs 2500; lr 0.03; L2 0.002; features standardized
using fit-window means/scales only) and `sportsedge/ufc_training.fit_platt`
(epochs 1500; lr 0.02). Both files are pinned in `SPEC_HASHES.txt`; the
build record re-pins them at build time.

### 4.3 Priors and missingness (exploration finding F3, discharged)

- The engine snapshot's shipped defaults (zeroed rates, 1500 Elo, 0.5
  recent-form / strength-of-schedule, 180-day layoff) do **not** carry
  into this construction. No feature is ever silently defaulted.
- **Tier 1 — whole pro record missing.** A fighter whose pro record is
  not found in the admitted source keeps their UFC-segment features,
  carries their P12 indicator = 1, and has each per-fighter pro-record
  quantity set to the median of that quantity over fighter-appearances
  in fit-window in-universe rows, grouped by the weight class of the
  bout in which each appearance occurred. A class with fewer than 30
  fit-window in-universe appearances falls back to the overall
  fit-window in-universe median. (*Fixed by this draft:* the 30-row
  fallback threshold.) All medians are computed on the fit window only.
- **Tier 2 — individual value uncomputable for a covered fighter**
  (e.g. a pro debutant's P11 rest days, a rate whose denominator is
  empty beyond the zero-rules already stated in §4.1, a missing date of
  birth behind `age_diff`, an unrecorded reach): the *differenced row
  feature* takes the median of that differenced feature over
  fit-window in-universe rows in the bout's weight class, with the same
  30-row fallback to the overall fit-window median.
- No missingness indicators beyond P12 and U5 are added; the §4.1
  vector is exact.
- Pro-record coverage is reported by era and segment share in the build
  record, and is measured in the judged window under §5's coverage
  floor. Missing historical fighter data remains uncertainty — it is
  never filled beyond the two tiers above (the DWCS note's rule,
  applied here).

### 4.4 Abstention

Bouts outside the §2 universe are not priced, not scored, and not
reported as part of this family. Abstention is part of the
construction, not a post-hoc filter.

## 5. Pinned parameters and measurement rules (review flag F-4)

- **Elo (pro-record and UFC-only alike).** Initial rating 1500.0;
  K = 32.0; expectation 1 / (1 + 10^(Δ/400)); result values win 1.0,
  loss 0.0, draw 0.5; no-contests produce no rating update; no
  margin-of-victory scaling. Adopted by reference:
  `sportsedge/ufc_training.update_elo` and the history builder's
  initial state.
- **Sequence rule.** Every rating sequence (pro Elo, UFC Elo, opponent
  means, rates) processes bouts in (date, event, fighter_a, fighter_b)
  order — the repo's chronological convention — with **date-granular
  snapshots**: all features for bouts on date *d* are computed from
  state accumulated over bouts dated strictly before *d*; date *d*'s
  updates are then applied in the stated order before date *d*+1 is
  processed.
- **Calibration error (the ≤ 0.05 gate) and all judged metrics.**
  ECE-10 exactly as computed by `sportsedge/ufc_training.evaluate`:
  10 equal-width bins over [0, 1], sample-weighted |mean predicted −
  mean outcome| per bin, probabilities clipped to [1e-12, 1−1e-12].
  Log loss and Brier use the same function's definitions, applied
  identically to the model, the market leg, and every baseline — one
  metric implementation for all legs (the V1 screen runner's
  `probability_metrics` precedent).
- **De-vig.** Proportional normalization: each side's implied
  probability (American odds: per the V1 runner's
  `american_to_implied`; decimal archive odds: 1 / odds) divided by
  the pair's implied sum. This is the V1 screen runner's `devig_pair`
  method, extended to decimal odds by the same implied-probability
  definition. No other de-vig method may be substituted.
- **Draws and no-contests in judged windows.** Excluded from scored
  rows in both legs; counted and reported by name (`DRAW_EXCLUDED`,
  `NC_EXCLUDED`) in the screen record; never resolved from another
  source and never filled. (V1's convention, stated for both legs.)
- **Floors (fixed by this draft** — the exploration left both to the
  preregistration):
  - **BestFightOdds join floor: ≥ 0.85** of in-universe judged-window
    bouts must join to a closing pair for both fighters under §2's
    identity rules. Every unmatched bout is enumerated. Below the
    floor, Leg A is void under §7.2 — a join failure, not
    `INSUFFICIENT_N`.
  - **Pro-record coverage floor: ≥ 0.90** of in-universe judged-window
    bouts must have both fighters *covered* — a record found in the
    admitted source, including a record that shows zero pre-UFC bouts.
    Bouts failing coverage are unscored and counted
    (`COVERAGE_EXCLUDED`); if scored n then falls below 100, the
    outcome is `INSUFFICIENT_N`.
  - Basis: the judged window holds ≈ 219 raw in-universe bouts (§6)
    against a ≥ 100 gate; both floors sit where a *systematic* join or
    coverage failure — the failure mode that would bias the segment —
    trips them, while ordinary name noise does not.

## 6. Windows, data roles, and expected counts (review flag F-3)

- **Design data:** everything dated ≤ 2025-12-31, including all of
  V1's windows and slices. Design data informs design only; it never
  judges.
- **Fit:** in-universe bouts ≤ 2019-12-31. **Calibration (Platt
  only):** in-universe bouts 2020-01-01 → 2022-12-31. (V1's windows,
  so the two constructions' design data coincide.) Expected
  in-universe counts, from the independent reviewer's replay over the
  pinned record: fit ≈ 2,396, calibration ≈ 690. These are
  expectations, not gates; §7.4 binds the build's reported counts.
- **Judged, Leg A:** in-universe bouts dated **2026-01-01 →
  2026-10-24**. (Review flag F-4g discharged: the exploration's
  unexplained 2026-09-30 end is moved to the pinned per-fight record's
  last date, so the 25 in-universe October 2026 bouts the earlier
  boundary discarded are included. The boundary is a property of the
  pinned record's coverage at freeze — a later re-pull of the mirror
  does not extend it.) Expected raw in-universe n ≈ **219** (194
  through Sep 30 + 25 in October; reviewer's replay, name-string
  identity) before §5 join/coverage losses, against the ≥ 100 gate:
  `INSUFFICIENT_N` is not the expected outcome, and the gate remains
  the count that survives the audits.
- **Judged, Leg B:** forward from freeze. The defined universe
  measured ≈ **44–47%** of ≈ 519 UFC bouts/year on the 2023–2025
  record — ≈ 235 in-universe bouts/year — so the §9 gate of n ≥ 150
  is roughly a **7–8 month** accrual. These measured figures replace
  the exploration's ~18–30% share / ~full-year expectation, which was
  anchored on the debut-any slice. The gate is the n; the leg runs
  until it is met or the owner closes the family.

## 7. Preconditions — admission audits (every gate sits in front of any build)

### 7.1 Pro-record source admission audit (binds the whole construction)

Before any build, the candidate source is audited. The admission act
names exactly **one** primary source; the other source of the
Tapology/Sherdog class serves as the audit's independent dated check.
Audit contents (*fixed by this draft*):

1. **Panel.** ≥ 50 fighters, including ≥ 15 whose pro debut predates
   2015-01-01 and ≥ 15 whose pre-UFC career is primarily outside the
   United States, as recorded by the sources.
2. **As-of reconstruction.** For each panel fighter, rebuild the
   record as of ≥ 2 dates (their UFC debut date; one mid-career date)
   from the primary source's dated bout list alone; compare
   bout-for-bout (date, opponent, outcome) against the independent
   dated source over the coverage both sources share. Pass requires
   **≥ 95%** of compared bouts to agree exactly, with every
   disagreement enumerated and classified (primary-missing /
   primary-extra / outcome-differs).
3. **Coverage measurement.** Fighters found / fighters sought,
   tabulated by debut era (pre-2015, 2015–2019, 2020+) and by primary
   pre-UFC region, over the panel and over all fighters in the design
   windows. The table is published in the admission record; §5's
   coverage floor governs the judged window itself.
4. **Identity.** §2's collision rule is applied; all collisions in the
   design windows are enumerated in the admission record.
5. **Documentation-timing lookahead (review flag F-5).** From the
   panel fighters' regional bouts, sample ≥ 100 bouts and check each
   against an independent dated source (dated event records;
   contemporaneous reports where they exist). Count (a) bouts present
   in the primary source's current-state record but absent from every
   independent dated source, and (b) bouts whose recorded result an
   independent dated source contradicts (later overturned or
   corrected). The audit reports the measured rate. **This draft
   states explicitly: documentation-date point-in-time is not
   achievable from these sources.** The construction's PIT standard is
   bout-date PIT — a bout enters a fighter's record only for target
   bouts dated after it — and the measured documentation-timing rate
   is carried into the screen record as a declared limitation (§11.3).
   If the measured later-added/overturned rate exceeds **5%** of
   sampled bouts, the audit **FAILS**: the channel is too large to
   treat as noise.

**FAIL of any part → the construction is VOID.** Its only mechanism is
this source; there is no fallback feature set and no substitute source
within this version.

### 7.2 BestFightOdds admission + join audit (binds Leg A only)

The admission act pins the archive's close semantics on the record:
book composition, and what "close" means in the archive (the last
recorded price before the bout, per the archive's own documented
definition as recorded at admission). Those semantics cannot be fixed
in this draft — they are a property of the archive that the admission
act must read and record; inventing them here would falsify the pin.
The join audit then applies §2's identity rules over the judged window
and measures the match rate against §5's join floor, enumerating
unmatched bouts and collisions. **FAIL → Leg A does not exist.** No
substitute baseline may be invented; the mdabbert mirror is refused as
a fallback (undocumented book/status, and only ~58 in-universe bouts
in its Jan–Mar 2026 priced tail). The construction may proceed to
Leg B only by explicit owner ruling, on the record that it would then
stand on zero historical evidence.

### 7.3 DK capture accrual (binds Leg B only)

The lane must actually bank UFC closes under the standing cadence.
Leg B's clock does not start at freeze; it starts when capture accrual
across cards is demonstrated on the record.

### 7.4 Segment count check (binds the build)

Before any judged run, the build record reports the in-universe fit
and calibration counts actually obtained. Fit < 500 or calibration
< 200 stops the build on the record. (*Fixed by this draft:* the two
floors, set well below §6's measured expectations and well above
degenerate.)

## 8. Leg A — historical screen on 2026 (one look)

Scored on the §6 judged window, against:

- **(A) Market baseline:** BestFightOdds closing odds, de-vigged per
  §5 — only if admitted under §7.2. Every figure labeled
  `ARCHIVE_CONSENSUS_CLOSE_NOT_DK`.
- **(B) Simple baseline:** a pro-record Elo-only reference — the §5
  pro-Elo expectation for side A, Platt-calibrated on the same
  calibration window (the program's naive-leg precedent).
- **(C) Existing-model leg (reported, not gated):** V1's construction
  restricted to the same in-universe judged rows, recomputed from its
  pinned pipeline. If that recomputation proves infeasible from the
  pinned artifacts, the gap is recorded — never papered over.

**PASS requires ALL of:**

| Criterion | Required |
|---|---|
| Judged n (in-universe, after §5 exclusions) | ≥ 100 — else `INSUFFICIENT_N`, a named outcome: not a pass and not a fail |
| Log-loss delta vs market (A) | ≤ 0.0 |
| Brier delta vs market (A) | ≤ 0.0 |
| Log loss vs simple baseline (B) | strictly better (model < (B)) |
| Calibration error (ECE-10, §5) | ≤ 0.05 |
| Per-half consistency | ΔLL vs (A) ≤ +0.01 in each of H1 (2026-01-01 → 2026-06-30) and H2 (2026-07-01 → 2026-10-24) separately — no single-period rescue |
| Flat-bet ROI at (A) closes | reported with the `ARCHIVE_CONSENSUS_CLOSE_NOT_DK` label; not gated in Leg A |

**One-look discipline.** The screen is declared in advance and run
exactly once, over the whole window, on the frozen construction, after
§11.2's no-peek rule has held from freeze to run. The named outcomes
are exactly: **PASS**, **FAILED_SCREEN**, **INSUFFICIENT_N**. A PASS
earns **eligibility for a forward preregistration only** — no
validation credit: the judged window is one the design was written
alongside (§11), and the market leg is an archive consensus, not
DraftKings. FAILED_SCREEN retires the construction; no retuning, no
second window, no amended criteria. Any change to the universe,
feature list, parameters, or windows after the freeze act is a new
version, judged on data after the change.

## 9. Leg B — forward DraftKings leg (the counting validation)

**Leg B's gates adapt the UFC promotion contract at segment scale;
they are not the contract's gates verbatim** — the contract's holdout
n ≥ 500 and debut-slice n ≥ 100 are replaced by the single segment
gate below, while its calibration-error (≤ 0.05) and market-delta
(≤ 0.0) values carry over unchanged. (Review flag F-6.) The contract's
remaining terms apply as the exploration states them — training-data
max age 45 days binds any promotion act that follows a Leg B pass, and
closing-market provenance is genuine by construction of this leg's
baseline; they are surrounding promotion terms, not Leg B scoring
gates (the V1 screen record's reading of the same max-age term).

The frozen construction is priced prospectively on lane `[UFC LINES]`
captures, after §7.3 accrual is demonstrated, and judged against
genuine DK closes. **Gates — all required:**

- Graded in-universe n ≥ 150 (expectation §6: ~7–8 months).
- Log-loss delta vs the DK close ≤ 0.0 **and** Brier delta ≤ 0.0.
- Log loss strictly better than the pro-Elo-only reference (§8 (B),
  same construction) run forward alongside on the same rows.
- Calibration error ≤ 0.05 (ECE-10, §5).
- Short-notice slice: reported once a booking-change source is
  admitted; until then recorded `NOT_IDENTIFIABLE` on every forward
  record — never silently dropped.
- Multiple testing per §10, with Leg A's segment ΔLL vs market as the
  family's declared primary metric carried into the accounting.

## 10. Multiple testing

**α = 0.05 / k**, k = the number of families validated program-wide on
the verdict date (the owner's standing policy; the V1 draft's §7
form). Primary test: Leg A's log-loss delta vs the market baseline (A)
on the §6 judged window. All other metrics, and both legs' secondary
figures, are reported, never gated on. Slicing (weight class, gender,
3- vs 5-round, debut vs ≤ 2-prior, promotion) is diagnostic only in
both legs.

## 11. Declared limitations and binding disciplines

### 11.1 Diagnosis-selection (review flag F-1 — declared limitation on any PASS)

The low-experience segment and the ≤ 2 threshold were selected
*because* V1's 2023–2025 slice table exposed the debut deficit as the
largest measured deficit (+0.0898) — among all the slices that table
exposed, the worst was chosen. Judging on bouts dated ≥ 2026-01-01
cures estimation leakage: no parameter of this construction was fit on
judged data, and its feature class (full professional records) did not
exist in V1. It does **not** cure hypothesis selection, and this draft
names that effect on the segment choice itself: regression to the mean
makes the segment's true deficit likely smaller than +0.0898, and the
segment's prior plausibility is correspondingly lower than a segment
chosen without seeing V1's table would carry. This limitation attaches
to any eventual PASS — a PASS shows the construction beat the closing
market on fresh bouts inside a data-selected segment, nothing
stronger — and the screen record must restate this paragraph when
reporting one.

### 11.2 No-peek rule for the judged window (review flag F-2 — binding)

The Leg A judged window's outcomes are **already observable**: the
pinned per-fight record contains 2026 bout results through 2026-10-24
(that is how the window's universe could be counted during design).
Leg A's integrity therefore rests on process discipline, bound here:

1. No design, feature, threshold, calibration, universe, identity, or
   window choice in this preregistration — or in the build that
   follows it — may be informed by any judged-window outcome, or by
   any statistic computed over judged-window outcomes. (Universe
   *counts* without outcomes, of the kind the independent review
   published, are the sole exception; any further count taken before
   the run is logged under rule 4.)
2. The BestFightOdds join may not be computed before this
   preregistration is frozen.
3. No judged-window aggregate of any kind may be computed by the build
   before the declared screen run.
4. **Enforcement.** The screen record must carry an attestation,
   signed by the builder and countersigned by the independent reviewer
   at the clearance step, that rules 1–3 held, listing every access to
   judged-window data between the freeze act and the run (including
   any counts taken under rule 1's exception). The reviewer verifies
   the attestation and the access log before the screen record is
   accepted; an unattested or contradicted screen record is not
   accepted.
5. Any contact with judged-window outcomes before the declared run
   **VOIDS Leg A**. The construction then stands or falls on Leg B
   alone, and only by explicit owner ruling on the record.

### 11.3 Documentation-timing (declared limitation, from §7.1 item 5)

Bout-date point-in-time is this construction's standard, and it is
defensible; documentation-date point-in-time is not achievable from
community-maintained current-state pages. A regional bout documented
only years later, or a result later overturned, can enter a later pull
of a fighter's record even though every bout date precedes the target
bout. The §7.1 audit measures this channel rather than assuming it is
zero, and its measured rate is restated in the screen record alongside
any result.

## 12. Governance

- This document is a **draft preregistration**. It freezes nothing
  until the owner's freeze act; adoption or amendment of any term is
  on the record before that act, and any change after it is a new
  version.
- Counted rows: **0**. No clock runs under this draft. No PLAY is
  created by anything in this package.
- `UFC_ML_PIT_RATING_V1` stays retired (FAILED_SCREEN, PR #2876); the
  unrestricted moneyline stays closed NO_CONSTRUCTION; DWCS and the
  other UFC families are untouched.
- `BUILD_SEQUENCE.md`, beside this draft, fixes the order of the work
  that follows adoption. Nothing in this package executes any of it.

*End of draft. Prepared Oct 28, 2026. Evidence states: V1 figures are
the merged PR #2876 record; the construction and diagnosis are the
PR #2923 exploration as independently reviewed (SOUND-WITH-FLAGS);
the pro-record source's point-in-time reconstructibility is
UNVERIFIED — establishing or refuting it is the §7.1 audit, which has
not run; BestFightOdds admission and join quality are UNAUDITED; no DK
UFC close has been banked.*
