# NFL Joint-Score Research Factory — Report (Oct 16, 2026)

**State: BUILT, research-only. NOT_VALIDATED. Production eligibility OFF.**
Branch `research/nfl-joint-score-factory-20261016`. Owner ruling executed:
joint scores enabled for explicitly labeled research use after review; the
canonical analytic engine (`artifacts/free_models`) is untouched, the G2
hold is untouched, and no sealed attempt was consumed.

## What was built

| File | Contents |
|---|---|
| `sportsedge/nfl_joint_score_research.py` | Frozen-artifact profile factory (PIT-gated) + simulator adapter + canonical-stage pricing wrapper |
| `artifacts/nfl_joint_score_research_harness.py` | Research harness CLI (NOT in the production card path) |
| `tests/test_nfl_joint_score_factory_20261016.py` | 11 tests: source chain, PIT tripwire, schema, identity, labels |

The factory reconstructs the owner-lane adapter (the /tmp skeleton did not
survive) as a repo module: `NFLIntegratedRegulationSimulator` (Engine A+C)
→ each sim's reconciled `to_market_row()` → joint score rows carrying
`home_score`/`away_score` plus every period field the derivative pricers
require (quarters, first half, second half regulation and with-OT).

**Profiles** come only from the frozen fitted artifact
`artifacts/football/nfl_prop_artifact_bundle_v1.json`
(`NFL_PROP_SHARED_PATH_2022_2025_V1`, fit scope REG 2022–2025, pinned by
`config/nfl_prop_model_freeze.json`). The loader verifies the whole freeze
chain before use: bundle part hashes, compressed hash, payload canonical
hash against both the bundle and the freeze config, and the
source-manifest hash. **PIT rule:** a fixture is eligible only when its
season is strictly after every fit season; provenance (artifact, hashes,
fit window, as-of rule) is recorded per team on every output. No market
data is read anywhere; a profile payload containing a market key is
refused outright (tripwire-tested). Field-position profiles use the
frozen structural class defaults (no per-team fit exists in the repo) and
special-teams rates are the fit's team aggregates — both provenances are
stated on the record, and no named kicker's status is claimed.

## Worked example (end-to-end, harness defaults)

SEA @ DEN, 2026 Week 7 (the Oct 15 TNF fixture; fit window strictly
prior), 2,000 sims, base seed 20261015, priced at that night's posted
DraftKings predicates (DEN TT 19.5 / SEA TT 20.5, total 40.5):

- Distribution: mean DEN 7.24, SEA 8.68, **mean total 15.92**.
- Identity check: pricer team-total probabilities equal the rows' own
  empirical fractions exactly (max diff 0.0).
- Through the canonical derivative stage: both team totals
  `PRICED_RESEARCH` (DEN Over 19.5 = 0.031, SEA Over 20.5 = 0.038),
  first-half total/spread priced, second-half totals priced under both
  OT rules, Q1 total priced.

## The honest headline — the level is not calibrated

The plumbing is proven; the distribution is not believable yet. A mean
total of **15.9 points** against a real NFL mean near 46 means every
Over probability above is mechanically correct and substantively
worthless: team totals "price" to ~97% Under at real lines. Play and
drive counts are realistic (~123 plays, ~22 drives per game in a 100-sim
probe); the scoring conversion inside the integrated A+C path is what
runs cold. The simulator module itself declares its numerical inputs
structural candidates with explicit validation blockers. **Until the
integrated path's scoring level is fitted and validated, these
probabilities are research artifacts — which is exactly what every label
on every output says.** No card, research or otherwise, should quote them
as estimates of real games yet.

## What remains blocked, and why

1. **First-half team totals** — still `SIMULATION_ROWS_EMPTY`. By design:
   that market has no pricer of its own (owner ruling, Oct 13, 2026); it
   is a period market and stays blocked until a compliant period
   team-total pricer exists. Unchanged by this build.
2. **Alternate lines through the canonical stage** —
   `ALTERNATE_PRICER_ERROR`. A defect found by this build:
   `nfl_phone_derivative_pricing.py` passes `None` for the unused
   alternate-lines argument and `derive_alternate_markets` iterates it,
   so single-sided alternate rows fail *whenever a distribution is
   supplied*. Production outcomes are unaffected today (no distribution
   is ever supplied on the canonical path, so `SIMULATION_ROWS_EMPTY`
   fires first). This build does not modify the production module; the
   harness preserves the stage outcome and prices alternates against
   the wrapped pricer directly in a labeled supplement (alt total 37.5
   Over = 0.008; alt spread DEN −2.5 home cover = 0.348). Fix for the
   integration lane: pass `()` instead of `None`.
3. **Any production or card use** — off by ruling and by calibration
   state. The factory has no importer in the card path.
4. **Distribution calibration/validation** — the real remaining model
   work: fit the integrated path's scoring level on PIT history and
   evaluate against baselines before any of these probabilities are
   quoted as estimates.

## Verification

- New battery: 11 passed. Neighboring suites (integrated regulation,
  team totals, unified phone, intake contract): 45 passed.
- Full suite: see the delivery note for the exact-head junit counts.
- Diff vs main: new files only — `free_models`, the derivative stage,
  the simulator, and every pinned module are byte-untouched.
