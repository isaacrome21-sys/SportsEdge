# NBA secondary player stat families — unvalidated research build

**Base main:** `4d4a07cc9d06dfb71dcd5d4a23c780ce93875b12`  
**Branch:** `feat/nba-secondary-props-empirical-20261020`  
**Build status:** DRAFT / NOT INDEPENDENTLY VERIFIED / NEW-FAMILY FORWARD SCREEN UNRUN.

## New scope
Research-only stat families `THREE_POINTERS`, `STEALS`, `BLOCKS`, `TURNOVERS`, `STEALS_PLUS_BLOCKS`, `DOUBLE_DOUBLE`, `TRIPLE_DOUBLE`. Source pool requires every matched played NBA game to contain actual PTS/REB/AST/STL/BLK/TOV/3PM as integers, verified season/player/team/position game and observed-at timestamps, plus independently attested source snapshots. Double/triple counts use **one same-game row across five stats** (two or three 10+ categories) rather than assuming separate box-score counts independent. No per-stat multiplicative shortcut.

Candidate family weights are same k=5 player same-season game distribution versus expanding position-group B1 (fallback all-positions if position pool <30), subject to ten prior played player games, 30 comparison game samples, strict pregame as-of, no same-day results, no DNP or absent-player fabricated zeros. Integer line pushes remain explicit. Source hash includes team, position, minutes, game clock, stat records, source SHA and observed-at. Those are **input evidence claims**, not authenticated external verification. All outputs `RESEARCH_UNSCREENED_NEW_FAMILY`, `eligible=false`, `NO_MARKET_TEST`, `conditional_on_participation=true`, `participation_model_verified=false`. No LIVE runner, quote binder, registry, frozen NBA prop Oct 21 clock, promotion or wagering surface touched.

**Limitations:** the reused mixture hyperparameter is NOT evidence these seven new families beat baseline; block until independent first-screen proper scores and separately verified available/tipped-off players. No historical valid DK paired odds/CLV or multi-outcome performance proved.

## Exact files (Git blob SHA-1)
* `sportsedge/nba_secondary_prop_empirical.py`: `4f15dd761e137019a216ab01728ce2baf633c42f`
* `tests/test_nba_secondary_prop_empirical.py`: `d485ab09c2b60867078bd514e45cdc3e45f32ddd`
* `research/nba_secondary_prop_20261020/SCREEN_SPEC_DRAFT.md`: `c003014c7d6d003e8f360f211c6d95b697bc0b1f`

## Tests and screen results
10 new synthetic pytest test functions authored, parameterized count rungs and hostility tests; **not independent green or live historical calibration**. The DRAFT screen proposal for 2026–27 forward games is predeclared separately and **UNRUN**. Same-game combo and strict future-result tests, DNP zero-handling, provenance, integer pushes and refusal states included. No data evidence/owner market pins admitted, so `INSUFFICIENT_DATA` / `NO_MARKET_TEST` until independent source authentication and first-score execution.

## Rocky verification handoff
Recompute individual same-game DD/TD milestones and combo from unaltered box rows, verify score-conserving no-vig O/U with integer push, independence not silently assumed, strict actual observed-at chronology, missing player and DNP exclusions, hash consistency, frozen NBA PTS/REB/AST/PRA file parity and no source of participation verification. Compare full suite failure set against base and no behavior drift. Draft remains unmerged and cannot change NBA market labels.
