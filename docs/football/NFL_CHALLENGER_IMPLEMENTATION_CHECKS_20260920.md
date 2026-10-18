# NFL challenger implementation checks — 2026-09-20

Research mechanics only. No historical holdout evaluated, no attempt consumed,
and no Model_P validation, Truth Gate, promotion, eligibility, staking, or OFFICIAL authority.

## Tested code

Probability readout fixes: commit `5ec8b3666c78b40e6397052f03f88e9018ac2d95`.
Possession engine and equivalence tests unchanged from `005c28a285c18eee5f1bbc5eb6cb04ee8f6f093c`.

- Reject corrupt TD components before computing anytime/two-plus probabilities.
- Reject invalid safety outcome counts and mismatched parent-summary row counts.
- Replace six failing duck-typed TD test fixtures with real attributed football paths.
- Preserve production path-type and participation checks.

## Local verification

Python 3.12.14, NumPy 2.3.5, PCG64; pytest 9.1.1.
The repository pins NumPy 2.5.3, so this local run does not certify the pinned CI environment.

67 focused pytest tests passed, plus 2 subtests:
`test_nfl_probability_markets.py`, `test_football_player_market_readouts.py`,
`test_nfl_probability_capability_audit.py`, and non-distribution
`test_nfl_possession_challenger.py` tests.

The three existing distribution test functions were invoked directly from the unchanged
test module. Each completed successfully with 200,000 reference and 200,000 vectorized
paths; no million-path retry was reached.

| Fixture | Existing seed (both implementations) | Runtime |
| --- | --- | --- |
| Near-even, high OT, safety | 4101 | 89.14 s |
| Lopsided home | 4201 | 87.01 s |
| Lopsided away | 4301 | 87.71 s |

All assertions in these existing functions passed, including mean scores, possessions,
drive-outcome shares, exact 3/7 mass and KS distances. Raw metric values were not
persisted by the existing helper; this records test outcomes, not a full evidence bundle.

## Remaining blockers

- The frozen contract requires independent recorded seeds; existing fixtures use the
  same seed for both implementations. These results do not establish full contractual
  equivalence. Correct and record the seed protocol before another acceptance run;
  preserve this observation rather than relabeling it.
- Current OT is explicitly a state-naive sudden-resolution baseline. Historical
  season-specific OT mechanics and their blocking fixtures remain unimplemented.
- PR merge remains blocked by reconciliation: current main
  `78aae277890d5ef8b02d72e1cc075150d07b1867` does not match the registered boundary.
  The observed gate failed `main_matches_reconciliation_boundary`, with 46 other
  reconciliation tests passing. Do not bypass or weaken this check.
- Full pinned-environment CI and final-head freeze/attestation remain required.

## SHA-256 identities

- Engine: `703db4d010622b984dcecc1420b0a5b81c79c50713f625a7b3b92030f441ef73`
- Equivalence tests: `db8d7280bca39dcd39e37fc7c833dba97408a54ea11b37d42976104668328a8b`
- Probability readouts: `f4f3d3b3120e509bbd93723627f277e7c48b94da7cf57e6c069c238f58550647`
- Probability tests: `ba26455d6cc6b7e8136b4d07baae71eed8ed45ebfd0b6a6b4ae23808fd4e5355`
