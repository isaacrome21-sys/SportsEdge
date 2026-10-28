# DESIGN + PREREGISTRATION (DRAFT) — UFC moneyline: point-in-time fighter rating from UFCStats career rates vs the market

**Status: DESIGN + DRAFT PREREGISTRATION — NOT FROZEN, NOT IN FORCE.**
Prepared Oct 27, 2026 under the owner's directive adding PGA, UFC and DWCS to
the program with every family carried toward clock-running / armed / screening.
**Freezing is the owner's act. No bout counts toward this test before its
freeze.** Nothing in this document starts a clock, verifies anything, or
creates a PLAY. PAPER / research only.

Family: `UFC / MONEYLINE_H2H` (flagship for UFC — the only market the repo's
market-surface config lists as engine-supported: `config/ufc_market_surface.json`,
engine `UFC_FIGHT_SIM`; method / rounds / distance markets are recorded there
as `unsupported_without_new_engine`).
Activation state today: **ENGINE + DESIGN EXIST, NO PREREGISTRATION** →
this draft moves the family to **PREREG DRAFT**; the historical screen in §6
is executable immediately once §3's data pull is pinned.
Sibling documents: `PGA_H2H_MATCHUPS_DESIGN_PREREG_DRAFT.md`,
`DWCS_DESIGN_NOTE.md` (same directory).

## 1. Relationship to what already exists (read first)

This is **not** a greenfield sport in the repo. `docs/ufc_model_design.md`
already specifies the production objective, feature set, model stack and
validation discipline; `sportsedge/ufc_engine.py` implements a
`FighterSnapshot` with exactly the rate fields §4 freezes;
`config/ufc_promotion_contract_v1.json` already fixes promotion gates.
This preregistration binds that stack's moneyline family to one frozen
candidate construction and one scoring protocol, adopting the promotion
contract's numbers verbatim as the pass criteria. Where this draft and the
design doc disagree, this draft governs the *test*; the design doc still
governs the *engine*.

## 2. Edge mechanism

UFC prices lean heavily on records, rankings and name recognition; the
quantitative record — striking and grappling rates against opponent quality —
is public on UFCStats but expensive to assemble point-in-time, so it is
under-weighted by the market, especially for low-profile prelim fighters and
short-notice replacements. A rating built only from pre-bout career rates
(opponent-adjusted) should disagree with price most exactly where the
market's information is thinnest. The construction is deliberately plain —
Elo + a calibrated logistic on frozen rate features — because the claim
being tested is that the *features* carry edge, not that a flexible learner
can find some.

## 3. Inputs — verified contents, tiered

| Input | Source | Tier | State |
|---|---|---|---|
| Every UFC bout, mid-2010 → present, with **Red/Blue American odds**, winner, date, location | Kaggle `mdabbert/ultimate-ufc-dataset` — **contents verified by direct read Oct 27, 2026**: per-bout rows, `Red Odds (American)` / `Blue Odds (American)` + derived profit columns, winner in {Red, Blue, Draw}; ~6,900+ priced rows across 2010–2026; GitHub mirror exists (`shortlikeafox/ultimate_ufc_dataset`, incl. an `upcoming.csv` with the upcoming event's odds) | FREE (Kaggle account for download; owner already holds Kaggle credentials in repo secrets) | NOT YET PINNED — fetch + sha256 pin via the standing Kaggle route |
| Per-fight striking/grappling stats for every UFC bout (feature reconstruction) | UFCStats via Kaggle `rajeevw/ufcdata` (`raw_total_fight_data.csv`, scraped from ufcstats.com event pages) + ufcstats.com itself for forward snapshots | FREE web | NOT YET ADMITTED |
| Fighter attributes (age, height, reach, stance, weight class) | UFCStats fighter pages (in both datasets above) | FREE web | NOT YET ADMITTED |
| Forward DK prices + pre-fight snapshots | Standing lines-lane capture (`[UFC LINES]` grammar exists in the run-it surface) | In-repo | Capture live for current cards |

**Provenance disclosure (material):** the mdabbert page does **not** document
which book its odds come from or whether they are openers or closes — one
recorded price per side per bout. They are therefore labeled
`RECORDED_PRICE_NOT_DK_CLOSE` everywhere in this test: a real market
baseline, but not the timestamp-authenticated DK close this program prefers.
§6's criteria are set against them as-is, and the forward leg (§6, Leg 2)
on genuine DK captures is still required before any promotion.

## 4. The construction (frozen at freeze; any change = new version)

Candidate `UFC_ML_PIT_RATING_V1`:
1. **Elo** per fighter, updated bout-by-bout in date order (K and margin
   rules fixed in the implementation spec; no future bouts in any update).
2. **Features** (both fighters, differenced): Elo; sig. strikes landed/min;
   sig. strikes absorbed/min; strike accuracy; strike defense; knockdowns
   per 15; takedowns per 15; takedown accuracy; takedown defense;
   submissions per 15; control seconds per 15; finish win/loss rates;
   recent win rate (last 5); opponent-adjusted strength of schedule; age;
   reach difference; stance matchup indicator; days since last bout
   (layoff); UFC bouts of experience. These are the `FighterSnapshot`
   fields in `sportsedge/ufc_engine.py`.
3. **Model**: logistic regression on the differenced features + Elo term,
   Platt-calibrated on the validation window only. The design doc's
   gradient-boosted challenger and 250k-draw Monte Carlo are **out of
   scope for V1** — challengers get their own preregistrations.
4. **Eligibility**: a fighter with zero prior UFC bouts is a DEBUT row —
   priced only via the prior (features at class medians + experience=0)
   and scored in its own slice (§6). Missing rate stats → the design doc's
   missing-data indicator + uncertainty penalty; never silent zeros.

## 5. Point-in-time rules (hard)

- Every feature for a bout is computed from fights dated **strictly before**
  that bout's date. Career aggregates are rebuilt from the per-fight record
  (rajeevw), never copied from a snapshot taken after the bout.
- **Mandatory pre-screen audit of the mdabbert precomputed columns:** before
  any run, spot-rebuild ≥ 25 fighters' feature rows from the per-fight
  record and compare against the dataset's shipped aggregates; if the
  shipped columns prove to include the bout itself (or later bouts), they
  are discarded wholesale and only rebuilt features are used. The audit
  result is recorded either way.
- Odds are evaluation-only. No market price enters the feature vector
  (design doc + program law).
- Short-notice / late-replacement bouts (either fighter changed inside
  14 days) are flagged and sliced separately — never dropped silently.

## 6. Validation protocol — criteria fixed in advance

**Leg 1 — historical chronological OOS screen (the executable test).**
Fit ≤2019 → validate (calibration only) 2020–2022 → **test 2023–2025,
untouched until this prereg is frozen**. Baselines: (A) **market** — the
§3 recorded prices, de-vigged; (B) **model** — an Elo-only reference
(the program's naive-leg precedent), plus the incumbent engine's
probabilities wherever a pre-fight archive exists (coverage is partial;
where absent, leg B is the Elo reference and the gap is recorded, never
papered over).
**Leg 1 PASS requires ALL of (adopted verbatim from
`config/ufc_promotion_contract_v1.json`):** test n ≥ 500; debut slice
n ≥ 100 scored separately; calibration error ≤ 0.05; Brier delta vs market
≤ 0.0 AND log-loss delta vs market ≤ 0.0; log loss strictly better than
the Elo-only reference; short-notice slice reported (required, not gated);
plus flat-bet ROI > 0 at the recorded prices on the test window (reported
with the provenance label of §3 attached to every figure).
PASS = SCREEN_PASSED / ARMED. FAIL = recorded FAILED_SCREEN; V1 retires.

**Leg 2 — forward DK leg (required for any promotion past ARMED).**
Frozen construction priced prospectively on lane captures; verdict under
the promotion contract's remaining terms (incl. training-data max age
45 days and closing-market provenance — genuine DK closes this time).
Minimums mirror Leg 1 (n ≥ 500 graded bouts) — roughly a full UFC year.

## 7. Multiple testing

- **α = 0.05 / k**, k = families validated program-wide on the verdict
  date (owner's standing policy). Primary test: Leg-1 log-loss delta vs
  the market baseline on the 2023–2025 window. All other metrics are
  reported, never gated on; slicing (weight class, gender, 3- vs 5-round,
  debut, short-notice — per the design doc) is diagnostic only.

## 8. Remaining UFC families — one-line sketches

- **Method of victory** — needs the design doc's joint-outcome Monte Carlo
  layer (KO/TKO vs SUB vs DEC shares); market surface marks it
  `unsupported_without_new_engine`; own prereg, only after the ML verdict.
- **Total rounds / fight goes the distance** — distance probability is a
  by-product of the same joint layer; own clock, own prereg.
- **Round of victory** — the design doc explicitly defers round-time
  simulation ("must not be inferred from method probabilities alone");
  last of the prop families.
- **SGP** — legs first (program law); no construction until ML + the
  relevant leg family both hold verdicts.
- **Live in-play** — NO_CONSTRUCTION; no in-play engine or feed exists.

## 9. Blockers

- Kaggle pull + hash pin of the two §3 datasets (route exists; owner
  already provisioned the credentials) — one step, unblocks the screen.
- The §5 PIT audit must run before any number from Leg 1 is quoted.
- DK-close provenance for Leg 2 depends on the lane's UFC capture staying
  healthy through a full season.

*End of draft. Prepared by Rocky (Muse) overnight Oct 27–28, 2026.
Evidence states: mdabbert dataset contents verified by direct read of the
dataset page Oct 27, 2026; repo artifacts (engine, design doc, promotion
contract, market surface) read on main at 318377dfa; all performance
figures are criteria, not results — no run has been executed.*
