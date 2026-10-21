# Build report — MLB M22 one-inning 2nd–8th score joint

**Base main verified at branch creation:** `2ed6ed711528070e8dc1ccadaeb49e086ba3620a`  
**Branch:** `feat/mlb-m22-inning-2-8-pit-research-20261020`  
**Status:** DRAFT, UNVERIFIED RESEARCH BUILD; *no changes to production pricing/eligibility/registry/labels/held-gate files.*

## What and why

Introduces one evidence-bound conditional-independence joint per inning n=2..8, constructed from strictly-prior complete historical **single-inning** counts, not a difference of F3/F5/F7 cumulative score distributions and not 5/9 scaling. Requires real game/team IDs, fully completed games with both halves actually played, positive integer run counts, one row per unique gamePk for the *exact* target inning, prior recorded completion/observation timestamps and hash-shaped source identity. No inaccessible fixture, partial historical inning, future or unverified timestamp silently falls into feature arrays. Each side uses average of its for-runs and opposing allowed-runs empirical marginal. The game-inning joint is the product of those marginals, shared by O/U 0.5/1.5, inning run line, and HOME/TIE/AWAY three-way winner readouts. Optional fixed m30 league prior requires at least 200 strictly-prior team inning observations.

***Critical limitations:*** (1) externally supplied historical source hashes are **not independently authenticated** by this code; feed manifest/capture evidence and PIT replay admission are separate; (2) marginal independence is a research model assumption, not a validated empirical truth; (3) `INNING_9_*` remains named **HELD** because bottom ninth is conditional on earlier score/walkoff and can be unplayed, and `RESULT_AFTER_INNING_N` is a *different cumulative* family; (4) no historical first screen, booked quote or against-market test exists.

No canonical deployment: `sportsedge.mlb_per_inning_gates` untouched. New readouts have `research_only=true`, `eligible=false`, `NO_MARKET_TEST`, `play_authority=false`, `staking_authority=false` and no price/EV fields.

## Exact staged source artifacts (Git blob SHA-1)

* `research/mlb_m22_inning_2_8_20261020/SCREEN_SPEC_DRAFT.md`: `a91bce54c72362b1494866c571d7569d6842ab99`
* `sportsedge/mlb_m22_inning_joint.py`: `9868540d683f9d2301be37d4d2cbfd476e5e1d25`
* `tests/test_mlb_m22_inning_joint.py`: `9474f316bfe9082059749590e179e32d2ce8680c`

## Test and screen state

* 13 pytest functions with parameterized test sets **authored**, not yet independently run or green-claimed. Tests cover seven innings, three-way TIE mass conservation, opposite signed run-line coherence, both totals rungs, duplicate gamePk, target leakage, future timestamps, same-day PIT fence, missing played half, official game length, source SHA, missing league sample for m30, invalid run inputs, zero game samples, hash binding, unsupported ninth and canonical gate hold.
* `SCREEN_SPEC_DRAFT.md` documents proposed one-shot 2025 PIT chrono evaluation against league-by-inning climatology, with Brier/log loss and block-bootstrap confidence intervals. **UNRUN**. No score metrics, sample N, mean result, truth gate or admissible market edges asserted. Owner must first admit a complete historical source manifest with observed-at lineage, before any historical evaluations. No data backfill.
* No third-party runtime deps changed.

## Hand to Rocky

Verify exact PR head and git diff; independently construct a strict pregame archive, hand-recompute at least one inning joint and three-way tie mass, prove RUNS 0.5/1.5 conservation and opposite signed run-line parity. Attack temporal evidence: duplicate gamePk, future observed-at, missing half and ninth inning, incomplete historical games, league prior threshold. Run new tests and nearby incumbent engine suites; compare failure set with base; confirm zero gate, registry, RUN IT or frozen-doc edits. If pass, continue normal update-to-main and fresh CI. **Do not merge based on this builder report.**
