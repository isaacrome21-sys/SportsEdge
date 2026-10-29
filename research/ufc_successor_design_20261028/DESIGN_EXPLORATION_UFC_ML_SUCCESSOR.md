# DESIGN EXPLORATION (DRAFT) — UFC moneyline after `UFC_ML_PIT_RATING_V1` FAILED_SCREEN: one restricted successor proposed; the all-bouts moneyline closed as NO_CONSTRUCTION

**Status: DESIGN EXPLORATION ONLY — NOT A PREREGISTRATION, NOT FROZEN,
NOT IN FORCE.** No engine has been built, no screen has been run, no clock
has started, and nothing here validates anything or creates a PLAY.
Prepared Oct 28, 2026 as a design-stage exploration of what, if anything,
may lawfully follow the retired flagship. Freezing anything in §3–§4 is
the owner's separate act. PAPER / research only.

Family: `UFC / MONEYLINE_H2H` (the only market `config/ufc_market_surface.json`
lists as engine-supported; every other UFC market remains
`unsupported_without_new_engine` and is out of scope here, as is DWCS —
a separate family under its own design note, requiring event-specific
validation by repo governance).

**Predecessor:** `UFC_ML_PIT_RATING_V1` — FAILED_SCREEN, PR #2876, merged
Oct 28, 2026. **V1 stays retired.** It is not resurrected, not re-tuned,
and not re-judged anywhere in this document. Its 2023–2025 holdout is
**design data only** for any successor: it informed V1, it informs this
diagnosis, and it may never judge a successor.

Primary records relied on (read firsthand on main `aed769f75`,
sha256 of the files as read):

| Record | sha256 |
|---|---|
| `research/ufc_moneyline_screen_20261028/SCREEN_REPORT.md` | `75a60285f27c933fc071dcbda566b358bdd17a6d0dd0016cdc457d0108814e50` |
| `research/ufc_moneyline_screen_20261028/screen_results.json` | `df0a1b1f31618fbf09d7d7e66c46d48477537eec8811d6d372fbedc23e838da9` |
| `research/ufc_moneyline_screen_20261028/PINS.json` | `ecbf19c047dddf267af86fe17550ce19bd0a707f5f34a4673747bfd40be8d944` |
| `research/new_sports_designs_20261027/UFC_MONEYLINE_DESIGN_PREREG_DRAFT.md` | `819762e90dbd4e3b14f226f7a686cca08d549d48fb93f0f57391043e776185ce` |
| `config/ufc_promotion_contract_v1.json` | `12bc19b48cc3a5e8c96b00599149452c2de6a0fa11e045bb80c64d6dd016b9aa` |

Freeze-coverage: this document's path was tested against
`config/freeze_reconciliation_registry_v1.json` with the repo matcher —
**NOT GOVERNED**. No config, registry, workflow, or engine path is
touched by this document.

---

## 0. Conclusion up front

1. **The all-bouts UFC moneyline is closed: NO_CONSTRUCTION.** V1 lost
   to the market in every measured slice with n ≥ 40 — most where its
   information was richest — and no inventoried free point-in-time
   source supplies the information classes (tape study, camp and injury
   news, weigh-in and money-flow signals) that plausibly make up the
   difference. A more flexible learner over the same features is a
   search of the same information set, i.e. tuning on the diagnosis.
   No successor for the unrestricted moneyline is proposed.
2. **One restricted successor is proposed: `UFC_ML_LOWEXP_PRORECORD_V1`**
   (§3). It prices only bouts where at least one fighter has ≤ 2 prior
   UFC bouts, and its mechanism is a *new information class* — full
   professional (regional + UFC) records — aimed at the single largest
   measured deficit, the low-experience segment, where the market
   demonstrably differentiates fighters that a UFC-only record renders
   identical. It abstains on all other bouts.
3. The proposal is **conditional**: it is void if the pro-record source
   fails the point-in-time admission audit in §5. Its historical leg
   exists only if the BestFightOdds closing archive passes its own
   admission and join audit; otherwise the market leg is forward-only
   (§4). Nothing in §3–§4 may be read as evidence the construction
   works — there is none yet.

## 1. Data inventory — what actually exists

Evidence states are stated per item: *read firsthand this session*
(Oct 28, 2026, on main `aed769f75` or the live workspace), *repo record*
(the repo's own documents), or *scoping-session verified* (Oct 27, 2026
scoping session, `research/new_sports_scoping_20261027/`).

### 1.1 In the repo

- **Engine and design lineage** (*read firsthand*): `docs/ufc_model_design.md`;
  `sportsedge/ufc_source.py`, `ufc_history.py`, `ufc_training.py`,
  `ufc_engine.py`, `ufc_promotion.py`, `ufc_runtime.py`;
  `scripts/build_ufc_training_artifact.py`, `build_ufc_live_inputs.py`,
  `run_ufc_full_model.py`; `.github/workflows/ufc-full-model.yml`;
  eight UFC test files incl. `tests/test_ufc_moneyline_screen.py`.
  Status in the repo's own words: moneyline only supported;
  `automatic_model_inputs: false`; the training artifact self-reports
  **UNVERIFIED** absent a promotion-contract pass. Code presence is not
  validation — nothing in this lineage has ever passed a market test.
- **V1's record** (*read firsthand*): the design draft (§0 table), the
  screen package `research/ufc_moneyline_screen_20261028/` (PINS.json,
  SCREEN_REPORT.md, screen_results.json, run_screen.py), and the
  promotion contract `config/ufc_promotion_contract_v1.json` (gates:
  holdout n ≥ 500, debut n ≥ 100, calibration ≤ 0.05, Brier and
  log-loss deltas vs market ≤ 0.0, training-data max age 45 days,
  closing-market provenance and short-notice evidence as hard gates).
- **The repo stores hashes, not UFC data** (*verified this session*):
  there are no bout-level UFC datasets in the tree. PINS.json pins five
  files by sha256; the bytes themselves live outside the repo and are
  re-pullable from the pinned commits:
  - Per-fight record — `Greco1899/scrape_ufc_stats` @ `5d6622ff…`
    (4 CSVs: events, fight results, fight stats, fighter tale-of-tape).
    The same UFCStats mirror the production history pipeline already
    consumes. Per the screen: rebuilt into 7,556 point-in-time
    training rows, 2010 → 2026-10-24.
  - Market / outcomes — the author's GitHub mirror of Kaggle
    `mdabbert/ultimate-ufc-dataset` (`shortlikeafox` @ `31d29415…`):
    `ufc-master.csv`, 7,177 rows, **6,924 priced rows**, dates
    2010-03-21 → 2026-03-28, one recorded American price per side.
    Provenance label everywhere: **`RECORDED_PRICE_NOT_DK_CLOSE`** —
    the dataset does not document the book or whether prices are
    openers or closes.
  - Workspace persistence note (*verified this session*): the pulled
    CSV copies used by the Oct 28 screen persist at
    `~/workspace/ufc-screen-20261028/data/` (all five files), and this
    session re-verified every file's sha256 against PINS.json —
    **5/5 match**, byte sizes included. The pin remains the record:
    any future run re-verifies hashes before use and re-pulls from
    the pinned commits if a copy is missing or mismatched.
- **Card/config artifacts** (*read firsthand*): `config/ufc_330_current.json`
  (a hand-built Aug 15, 2026 card override) and
  `config/ufc_run_request_2026-08-25.json` — evidence the old lineage
  priced live cards by hand assembly, not that any price was validated.

### 1.2 The forward price feed — grammar exists, no banked data

The V1 design (§3) records the standing lines lane's `[UFC LINES]`
capture as the forward DraftKings source. As of this session (*read
firsthand*): the lane registry (61 entries, the Oct 28 slate) contains
**zero UFC entries**, and `lane_intakes/` holds **no UFC capture
files** — no DraftKings UFC closing line has yet been banked. The
forward leg of any UFC construction therefore depends on capture
actually accruing over a season (the same dependency V1's §9 named);
it is a precondition to verify, not a fact to assume (§5.3).

### 1.3 What does NOT exist (named, not assumed)

- **Historical DraftKings closing lines for UFC** — no source, in-repo
  or free, is known to this program. No UFC number may ever be labeled
  a DK close historically.
- **A timestamped, documented-book historical odds archive in the
  repo** — none. The mdabbert price is one undocumented number per
  side; whether it is an opener or a close is unknown.
- **A booking-change / short-notice archive** — neither pinned source
  records booking changes. V1's short-notice slice was
  **NOT_IDENTIFIABLE** historically, and the engine's
  `late_replacement_diff` feature is structurally zero in historical
  data for the same reason. Any successor inherits this gap until a
  booking source is admitted.
- **Pre-UFC (regional) bout records joined to UFC fighters** — not in
  the repo, not pinned, not admitted. UFCStats and its mirrors carry
  UFC bouts only; a debutant's regional career is invisible to every
  source V1 used. This is the gap §3's mechanism needs filled — by an
  *admitted* source (§5.1), not by assumption.
- **A DWCS historical slice** — the training artifact records
  `dwcs_specific_validation: UNVERIFIED`; DWCS is out of scope here
  regardless (§0).

### 1.4 Candidate free sources for admission (NONE admitted)

Per the Oct 27 scoping session (*scoping-session verified*) and, for
BestFightOdds, a web check this session confirming the archive and the
`balaustrada/ufcscraper` tooling exist as described:

| Source | What it would give | Point-in-time assessment |
|---|---|---|
| **BestFightOdds** closing-odds archive (via `ufcscraper`) | Per-fight closing odds across books — the standard free MMA closing archive; the candidate market baseline for a 2026 historical screen | Closes are historical facts and PIT-safe *as prices* if the "close" semantics (which books, what timestamp rule) are pinned at admission. Consensus/archive odds, **not DraftKings** — label would be `ARCHIVE_CONSENSUS_CLOSE_NOT_DK`. Join quality (fighter-name matching, collisions, match rate) is **unaudited**. |
| **Tapology / Sherdog** fighter records | Full professional bout histories including regional fights, with dates and promotions — the only identified free source class for pre-UFC records | PIT reconstruction (a fighter's record *as of* a bout date, from dated bout lists) is plausible but **UNVERIFIED**: page content is current-state, records are community-maintained, coverage varies by era and region, and no as-of reconstruction has ever been audited in this program. No API; terms-of-use and rate care required. Admission audit specified in §5.1. |
| **ufcstats.com** direct | The underlying stats site | Bot-gated from this runtime (scoping session); the Greco1899 mirror route (§1.1) remains the path. The mirror's own freshness must be re-verified at each pull (community-maintained). |
| **ESPN MMA API** | Schedules, results cross-checks | Partial odds surfaces, shallow stats; cross-check only, never a primary source. |
| **Kaggle `rajeevw/ufcdata`** | An older UFCStats scrape | Snapshot staleness varies; superseded by the Greco1899 mirror for the per-fight record. Design data at most. |

Paid odds-history vendors remain **NO** under the free-only law, as
does OddsPortal scraping. Nothing in this table is usable until its
admission act lands.

## 2. Why V1 failed — diagnosis

All figures from the merged screen record (test window 2023-01-01 →
2025-12-31, n = 1,291 scored bouts; fit ≤ 2019, Platt calibration
2020–2022; market baseline = de-vigged recorded prices,
`RECORDED_PRICE_NOT_DK_CLOSE`).

**Headline:** model log loss 0.6443 vs market 0.5887 (**Δ +0.0556**);
Brier 0.2263 vs 0.2016 (**Δ +0.0247**); calibration error 0.0405
(passed ≤ 0.05); Elo-only reference log loss 0.6821 (the model beat
it by 0.0378 — the career-rate features carry real signal); flat-bet
ROI at recorded prices **−2.18%**.

**Slice deltas (Δ log loss, model − market; positive = model worse):**

| Slice | n | Model LL | Market LL | ΔLL |
|---|---|---|---|
| All test | 1,291 | 0.6443 | 0.5887 | +0.0556 |
| UFC debut (either fighter) | 231 | 0.6650 | 0.5752 | **+0.0898** |
| 5-round | 141 | 0.6462 | 0.6207 | +0.0256 |
| 3-round | 1,150 | 0.6441 | 0.5848 | +0.0593 |
| Male | 1,095 | 0.6456 | 0.5914 | +0.0542 |
| Female | 196 | 0.6371 | 0.5737 | +0.0633 |

Every weight class with n ≥ 40 also loses (closest: Bantamweight
+0.0137; worst: Middleweight +0.0931). Two asymmetries carry the
diagnosis:

- **On debuts, the market is better than its own overall mark**
  (0.5752 vs 0.5887) and *more accurate* (69.7% vs its 69.5%
  overall), **while the model is worse than its own overall mark**
  (0.6650 vs 0.6443) with calibration error 0.0996 — two and a half
  times its overall 0.0405.
- **On debuts, the model adds ~nothing over Elo-only** (0.6650 vs
  0.6691), because a debutant's career-rate features are not data —
  they are the engine's defaults (zeroed rates, 1500 Elo, 0.5
  recent-form/SoS), identical for every debutant.

### 2.1 Construction flaws a successor may lawfully address

- **F1 — a missing information class for low-experience fighters.**
  Every fighter with no UFC bouts is feature-identical to every other
  such fighter under V1, whatever their actual professional history.
  The market differentiates them — via regional records, tape, and
  reporting that exist before the bout. The largest measured deficit
  (+0.0898) sits exactly on this blind spot. This is an information
  gap, not a tuning gap, and it is the only flaw with a mechanism
  sized to its deficit.
- **F2 — spec/implementation drift in the feature vector.** The V1
  design (§4) lists knockdowns per 15, control seconds per 15, finish
  win/loss rates, and a stance-matchup indicator; the frozen
  `ufc_training.FEATURES` vector omits all four (the history
  snapshot's knockdown/control fields exist but are unused), while
  carrying `late_replacement_diff`, structurally zero in all
  historical data. A successor uses the full snapshot field set.
  Same information class as V1, so the expected gain is hygiene, not
  the mechanism — stated as such.
- **F3 — debut prior treatment never implemented as designed.** The
  design promised class medians for debut rows; the screen records
  that the engine has no operational counterpart to that wording, and
  zeroed-rate defaults shipped instead. A successor specifies its
  low-experience priors explicitly and reports pro-record coverage
  per era instead of hiding missingness in defaults.

### 2.2 Market-efficiency facts no successor should expect to beat

- **E1 — the deficit is universal, not local.** V1 loses in every
  slice with n ≥ 40, including 5-round main events (+0.0256), where
  its public-record information is deepest. The recorded market price
  aggregates information classes — tape study, camp and injury news,
  weigh-ins, money flow — that **no inventoried free point-in-time
  source contains**. On this evidence there is no identified
  mechanism by which any full-universe construction over public
  career rates closes a +0.056 log-loss gap, and the design doc's
  gradient-boosted challenger would search the same information set.
- **E2 — the market strengthens where public stats thin out.** Its
  debut-segment edge (E-asymmetry above) is the signature of a
  private-information advantage, not of a mispriced segment waiting
  for a better fit of the same features. Absent a new information
  class (F1), expect the same ordering at any sample size.
- **E3 — the baseline caveat cuts against comfort, not against the
  verdict.** V1 was judged against an undocumented recorded price.
  If those prices are closes, the bar was the genuine one; if they
  are openers, the true closing gap is larger. Either way the sign
  is not in doubt — and a successor must be judged against a
  *documented* close (admitted archive or forward DK), never against
  a softer baseline chosen after the fact.

## 3. The one successor construction — `UFC_ML_LOWEXP_PRORECORD_V1`

*(Working name in program style. Design only: unbuilt, unscreened,
unfrozen. Any build requires its own preregistration adopting or
amending these terms, and the owner's freeze act.)*

**Claim (narrow, falsifiable).** In bouts where at least one fighter
has ≤ 2 prior UFC bouts, a rating built on **full professional
records** — every sanctioned pro bout, regional and UFC, rebuilt
point-in-time — differentiates fighters that a UFC-only record
renders identical, and can beat the closing market **in that segment**.
The construction prices nothing outside the segment (abstention is
part of the construction, not a post-hoc filter) and makes no claim
about the unrestricted moneyline, which §0 closes.

**Universe (part of the construction, frozen at preregistration).**
A bout is in-universe iff either fighter has ≤ 2 completed UFC bouts
strictly before the bout date. (Design basis: V1's debut-any slice was
17.9% of its test window and is the only low-experience slice V1
measured; the ≤ 2 threshold is an extrapolation from it, recorded as
a design choice — **not** a measured optimum, and not tunable on
judged data.)

**Features** (both fighters, differenced; computed strictly before
the bout date; odds never enter the vector — program law):

- Pro-record Elo: an Elo over **all** sanctioned pro bouts in date
  order (UFC + admitted regional record), replacing UFC-only Elo.
- Pro experience: pro bouts; years since pro debut; bouts in the
  trailing 24 months.
- Pro performance rates: pro win rate and finish rate (overall and
  last-5-pro-bouts), rebuilt from the dated bout list.
- Pro opponent quality: mean pro Elo of prior opponents (the regional
  analogue of strength of schedule).
- Feeder/major-promotion exposure: share of pro bouts in a named
  promotion set (list frozen at preregistration; candidate set:
  DWCS, LFA, Cage Warriors, Invicta FC, ONE Championship, PFL,
  Bellator, RIZIN).
- UFC segment: for each fighter's UFC bouts to date (0–2), the full
  UFCStats snapshot field set — V1's `FEATURES` **plus** the four
  groups F2 restores (knockdowns/15, control sec/15, finish win/loss
  rates, stance matchup).
- Physical/temporal: age, reach, height diffs; days since last pro
  bout (layoff measured on the pro record, not the UFC record).

**Learner.** Plain logistic regression on the differenced features +
Platt calibration on the calibration window only — deliberately the
program's V1 philosophy: the claim being tested is that the *new
information class* carries edge, not that a flexible learner can
find some.

**Priors and missingness.** A fighter whose pro record cannot be
found in the admitted source is **not** silently defaulted: the row
carries a `NO_PRO_RECORD` indicator with segment-and-class medians
computed on the fit window only, and the build record reports
pro-record coverage by era and segment share. If coverage in the
judged window falls below the preregistration's floor, the affected
rows are unscored and counted, never filled (the DWCS note's
"missing historical fighter data must remain uncertainty" rule,
applied here).

**DWCS boundary (reading, for the preregistration to confirm).**
DWCS *bouts* are not in this universe (separate family; repo
governance requires event-specific DWCS validation). A fighter's
DWCS *appearances* are sanctioned pro bouts and count in their pro
record features.

## 4. Design data vs judged data, and draft screen criteria

**Design data (seen; informs design; never judges):** everything
dated ≤ 2025-12-31, including all of V1's windows and slices.
**Fit / calibration:** in-universe bouts with features rebuilt
point-in-time — fit ≤ 2019-12-31, Platt calibration 2020-01-01 →
2022-12-31 (V1's windows, so the two constructions' design data
coincide; segment counts to be reported in the build record — if the
segment fit or calibration count is degenerate, the build stops and
reports rather than proceeding).
**Judged data:** bouts dated ≥ 2026-01-01 only — disjoint from, and
chronologically after, all design data. Any change to the universe
threshold, feature list, or windows after a judged leg opens makes a
new version, judged on data after the change.

### Leg A — historical screen on 2026 (conditional; §5.2)

In-universe bouts 2026-01-01 → 2026-09-30, scored against:

- **(A) Market baseline:** BestFightOdds closing odds, de-vigged —
  *only if admitted* under §5.2, labeled `ARCHIVE_CONSENSUS_CLOSE_NOT_DK`
  on every figure.
- **(B) Simple baseline:** a pro-record Elo-only reference
  (Elo expectation over the pro record, Platt-calibrated on the same
  calibration window) — the program's naive-leg precedent.
- **(C) Existing-model leg (reported):** V1's construction restricted
  to the same in-universe rows, recomputed from its pinned pipeline.

**Forward-only caveat (explicit):** if the BestFightOdds admission or
join audit fails, **Leg A does not exist.** The mdabbert mirror's
priced rows end 2026-03-28 and its in-universe 2026 subset is too
small and too undocumented to judge on; no substitute baseline may
be invented, and the construction proceeds to Leg B only by explicit
owner ruling, on the record that it would then stand on zero
historical evidence.

**Draft Leg A criteria — PASS requires ALL of:**

| Criterion | Required |
|---|---|
| In-universe judged n | ≥ 100 (else `INSUFFICIENT_N` — a named outcome, not a pass and not a fail) |
| Log-loss delta vs market (A) | ≤ 0.0 |
| Brier delta vs market (A) | ≤ 0.0 |
| Log loss vs simple baseline (B) | strictly better |
| Calibration error | ≤ 0.05 |
| Per-half consistency | ΔLL vs (A) ≤ +0.01 in each of 2026 H1 and H2 separately (no single-period rescue) |
| Flat-bet ROI at (A) closes | reported with provenance label; not gated in Leg A |

A Leg A PASS earns **eligibility for a forward preregistration only**
— no validation credit: the judged window is one the design was
written alongside, and the market leg is an archive consensus, not
DraftKings. A Leg A FAIL retires the construction; no retuning, no
second window.

### Leg B — forward DraftKings leg (the counting validation)

The frozen construction priced prospectively on lane `[UFC LINES]`
captures, judged against genuine DK closes under the promotion
contract's remaining terms (training-data max age 45 days;
closing-market provenance genuine). Draft gates, mirroring the
contract at segment scale:

- In-universe graded n ≥ 150 (at the segment's historical ~18–30%
  share of ~500 UFC bouts/year, roughly a full UFC year — stated as
  an expectation; the gate is the n, and the leg runs until it is
  met or the owner closes the family);
- log-loss and Brier deltas vs the DK close ≤ 0.0; log loss strictly
  better than the pro-Elo-only reference run forward alongside;
- calibration error ≤ 0.05;
- short-notice slice reported once a booking source is admitted,
  else recorded `NOT_IDENTIFIABLE` (never silently dropped);
- multiple testing: α = 0.05 / k at verdict per standing policy,
  with Leg A's segment ΔLL vs market as the family's declared
  primary metric carried into the accounting.

## 5. Preconditions and kill conditions

1. **Pro-record source admission audit (gates everything).** Before
   any build: PIT reconstruction test on a sampled fighter panel —
   as-of records rebuilt from dated bout lists checked against an
   independent dated source; era and region coverage measured
   (pre-2015 and non-US scenes explicitly); name-identity collision
   handling specified. **FAIL → the construction is void.** Its only
   mechanism is this source; there is no fallback feature set. This
   is V1 §5's shipped-aggregate audit discipline applied to the new
   source.
2. **BestFightOdds admission + join audit (gates Leg A only).**
   Close semantics pinned (book composition, what "close" means);
   fighter-name join match rate at or above a floor fixed in the
   admission act; collisions enumerated. FAIL → Leg A void (§4
   caveat); the construction may proceed to Leg B only by explicit
   owner ruling.
3. **DK capture accrual (gates Leg B).** The lane must actually bank
   UFC closes (§1.2: none banked as of this writing). Leg B's clock
   is meaningless until capture is shown to accrue across cards.
4. **Segment count check (gates the build).** Fit/calibration
   segment counts reported before any judged run; degenerate counts
   stop the build on the record.

## 6. Governance

- This document is a **design exploration**. It preregisters nothing,
  freezes nothing, builds nothing, screens nothing, starts no clock,
  and creates no PLAY. PAPER / research only.
- `UFC_ML_PIT_RATING_V1` remains **RETIRED** (FAILED_SCREEN, PR
  #2876). This exploration does not resurrect, amend, or re-judge it;
  its 2023–2025 holdout is design data for successors and may never
  judge one.
- `UFC_ML_LOWEXP_PRORECORD_V1` is a **name for an unbuilt design**.
  Building it requires: the §5.1 admission act, its own
  preregistration (adopting or amending §3–§4 on the record), and the
  owner's freeze act before any bout counts.
- Method / rounds / distance / round-of-victory families: untouched
  by this document; each still needs its own engine work and
  contract, and none is implied by anything here.
- DWCS: untouched; remains capture + accrual under its own note.

*End of exploration. Prepared Oct 28, 2026. Evidence states: V1
figures are the merged PR #2876 record, read firsthand this session;
inventory claims are labeled per item in §1; the pro-record source's
point-in-time reconstructibility is UNVERIFIED — establishing or
refuting it is the §5.1 audit, which has not run.*
