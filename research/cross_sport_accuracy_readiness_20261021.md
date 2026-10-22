# Cross-sport model accuracy / 99-score integrity — first audit pass

**Evidence date:** Oct 21, 2026 CT. Source main pinned for this pass:
`6cc758128af65b62dfd8c1fa12c08e0adb17d65e`.

**Status: ACCURACY NOT REPAIRED; RESEARCH-ONLY.** This is a cross-sport
readiness and presentation audit, **not** a test showing the models beat
markets, an authorization to change the forward clocks, or a proposal to
activate a model. No historical capture is backfilled and no frozen evaluator
or attempt budget is changed.

## Reproduced test baseline

- Repo `tests/` on pinned main, Python 3.12, local `numpy 2.3.5`:
  **9,200 passed, 6 skipped, one failed** in 201.79 seconds. The single
  failure was `test_nfl_v2k_attempt1_runner.py::test_preflight_enforces_frozen_identity_and_path_rules`:
  `V2K_RUNTIME_NUMPY_MISMATCH:2.3.5`. It is an **expected frozen-runtime
  refusal**, not model-accuracy evidence.
- With isolated **NumPy 2.5.3** as required by the frozen identity,
  **that exact test passed**. No attempt was executed or budget spent.
- New independent regression unit tests: **10/10 passed**, covering
  NFL/CFB/MLB fake BEST+99 displays; unsupported input authority claims;
  canonical/config inventory; distinguishing DRAFT — NOT FROZEN from FROZEN;
  prereg hash mismatch, missing hash, path escape and unsupported statuses.

## What can and cannot be tested today

| Machine-readable instrument | Inventory | Accuracy finding |
|---|---:|---|
| Canonical MLB + NFL markets | 89 (38 MLB, 51 NFL) | 27 price-capable; **pricing does not establish accuracy** |
| Universal forward-validation family configs | 39 | 35 DRAFT — NOT FROZEN; four frozen NBA PTS/REB/AST/PRA without a countable verdict attached to this audit |
| Canonical markets without one of these 39 configs | 58 | Some are blocked/no engine and some have sibling frozen instruments; **do not interpret as 58 missing tests without reconciliation** |
| New scored paired historical/forward rows in this audit | 0 | **NO ACCURACY OR MARKET-BEAT CLAIM** |

Exact per-market structural detail is emitted deterministically by
`scripts/audit_cross_sport_accuracy_readiness.py` into the versioned JSON
report (`research/cross_sport_accuracy_readiness_20261021.json`, SHA-256
`9aaed9421c57ca1b632b3b4ad1d4cb670e6c17df8a183d5955916a88e6ea`).
The script verifies the actual frozen prereg SHA-256 when a config is
marked FROZEN; DRAFT strings containing the word “FROZEN” do not pass.

The project's Oct 20 forward program separately names **55 MLB, 51 NFL,
49 CFB, 19 NBA readiness rows, and three CBB game families**. Its larger
family map, sealed sibling tests, and capture gaps remain authoritative;
the 89-market canonical scope here is a **subset**, not a replacement.
NHL/UFC/PGA were parked at that program's source date. No assertion of
recent unpark/deployment is made by this audit.

### Existing independent accuracy evidence (not newly run here)

- **NBA game lines:** raw V1 MONEYLINE / SPREAD / TOTAL failed its reported
  historical market-accuracy checks; all remain WATCH with numeric score
  withheld on main. The newer pair-mean totals V3 at DRAFT #2469 failed
  its preregistered historical screen (19.3001 vs V2 18.9770 RMSE).
- **NFL main lines:** prior-driven moneyline/spread probabilities and total
  levels are held as WATCH in `artifacts/free_models.py`. This repo's
  `research/forward_validation_program_20261020/PROGRAM.md` separately
  tracks the LEVEL v2 totals forward leg and frozen player-prop tests.
- **MLB:** game Lane A previously `DOES_NOT_BEAT_MARKET`; 13 batter
  calibration families failed their baseline screens. Existing pitcher
  studies and closed families retain their own evaluation/attempt rules.
- **CFB:** game and player family registration/identity/capture holds remain;
  the C10 QB yards candidate failed its baseline per the program map.
- **CBB/NHL/UFC/PGA:** no claimed newly validated markets; where no counted
  quote+outcome sample exists this pass does not invent one.

### Reproduced misleading-confidence mechanism

The generic NFL/CFB/MLB PNG renderer previously copied a producer's
`pick`/`BET`/`ACTIONABLE` label into **BEST PLAYS**, and copied
`score_0_100`/`confidence_score` into **SCORE**, without an independently
verified accuracy verdict. But the NFL Score B rule itself explicitly calls
its result a **qualification/role score**, and MLB's Score B likewise
measures path count, price freshness and push handling — not probability
calibration. A 99 or 100 therefore did **not** establish a 99–100% chance.

This change fixes that **presentation failure only**, on the generic PNG
path: keep raw sources/odds/estimates/EV intact in source JSON, show at most
RESEARCH rows, withhold numeric SCORE, unvalidated model probabilities,
EV and edge in the shareable graphic, and show **NO VERIFIED PLAYS**. Raw caller-provided
approval flags cannot bypass that graphic boundary; it has no authenticated
owner/verdict binding. It does **not** alter model estimates, card engines,
other renderers, archived studies, or market eligibility.

## Path to actual accuracy improvements

1. **Data first:** independently resolve every game's/player's event ID,
   bookmaker, paired sides, first observable entry, final real pre-event
   close, outcome finalization, and pricing-code version. Missing/late
   receipts remain `CLV_MISSING` and are never reconstructed.
2. **Correct comparator and metrics:** compare each family on identical
   events, sides and timestamps against a frozen incumbent and admitted
   market, with Brier/log-loss for outcomes, proper distribution scores
   and RMSE/MAE for quantitative predictions, game-cluster uncertainty,
   calibration, price-aware settlement and CLV. Never select a candidate
   from in-sample performance or from the share of OVER vs UNDER picks.
3. **Model diagnosis by family:** NBA/NFL/CFB game-score *level, margin,
   dispersion and correlation* separately; MLB batter/pitcher *usage,
   starter availability, opponent/park and tail probabilities*; football
   and NBA props *minutes/snaps/participation and joint-stat correlation*.
   Prepare independent challengers with preregistered training/calibration/
   untouched test folds, without looking for a favorable subset after a fail.
4. **Release:** no family is promoted by this readiness audit, by a unit
   test pass, or by the new graphic labels. Actual market beat needs a
   prospective preregistered verdict, then independent Rocky/Muse review
   and the owner's explicit promotion decision.
