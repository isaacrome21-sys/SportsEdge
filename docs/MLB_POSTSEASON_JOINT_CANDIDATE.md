# MLB postseason joint-path candidate

Status: UNVALIDATED RESEARCH. NOT Model_P · NOT Truth Gate · NOT OFFICIAL.

This candidate clean-ports the four implementation/test files from PR #700,
commit `c711cb681b8337d190b6cd6b048605194d9e99e7`, and repairs game-state behavior.
The original PR remains open; it has not been declared redundant or closed.
The frozen V7 simulator, registry, policies and deployment flags are unchanged.

## Implemented repairs

- Required `rules_mode`: REGULAR_SEASON or POSTSEASON, bound into path identity.
- Postseason extras begin empty; regular-season extras use the preceding batter
  at second with unearned-run treatment.
- Ordinary walk-offs stop counting at the winning run. Out-of-park home runs
  count every runner and the batter. Hit credit on ordinary walk-offs is limited
  by the bases advanced by the winning runner, assuming the batter runs it out.
- A sacrifice fly cannot score a run when its catch is the third out.
- Nonfinite probabilities fail input validation.
- A half-inning reaching the 1,000-PA computational limit or a game unresolved
  after 30 innings fails the entire run. No synthetic winner or discarded path.
- Aligned final game scores and hitter PA/K counts accompany player samples.
- Research readouts derive ML, run line, total and supported hitter/pitcher
  counts from the same path set, preserve pushes, and enforce player-role binding.
- Stolen-base markets, first-HR, period markets and other unimplemented readouts
  raise explicit errors; a placeholder zero is not used as their probability.

Entry points:

- `sportsedge.dfs.mlb_joint_paths.simulate_mlb_joint_paths`
- `sportsedge.research.mlb_joint_market_readout.read_joint_research_probability`

Input PA, pitch-count, hook and baserunning probabilities are mandatory caller
inputs. No default fitted values are supplied. Numerical fixtures in tests are
synthetic engineering fixtures only.

## Limits that still prevent deployment

This is not connected to the production game registry or RUN IT as an approved
model. The existing V7 game engine's postseason limitations therefore remain a
production blocker until a separately validated replacement is admitted.

The ported fitter computes empirical frequencies and rejects non-prior event
times. It requires a FROZEN policy object, but that object alone does not establish
governed policy approval. Event timestamps and source hash strings alone also do
not prove historical information availability. Archived source bytes, capture
times, entity binding and independent PIT verification remain required.

The existing simplified path model still lacks fitted/state-conditioned coverage
for all baseball events and decisions: steals/caught stealing, substitutions,
errors and earned-run reconstruction, dropped-third-strike advancement,
runner outs, and full managerial/bullpen selection. Marginal outcome and pitch
counts are sampled independently; supplied hitter profiles distinguish starter
from bullpen but are not intrinsically conditioned on a specific opposing pitcher.
These limitations can affect core totals as well as props. No accuracy claim is
made from structural conservation tests.

## Exact finish requirements

1. Produce and independently audit market-blind, strictly-prior PA, pitch-count,
   hook and baserunning observations with archived byte/time provenance.
2. Resolve structural coverage gaps above before freezing/evaluating a new
   candidate. Do not patch frozen production inputs or reuse incumbent evidence.
3. Fit under the separately approved policy, with support checks and explicit
   missing-cell failures; retain policy/source/model hashes.
4. Validate game and player distributions in temporal holdouts: calibration,
   distributional scores, workload/tail behavior, market settlement and production
   parity. Engineering tests cannot fill this evidence.
5. Capture actual same-book paired DraftKings prices prospectively; preserve
   observed timestamps and closing provenance. Do not reconstruct the failed
   2026 forward window from this candidate.
6. Pass the existing governed promotion process before OFFICIAL output.

The current `config/mlb_prop_evidence_groups.json` has six MISSING groups:
HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE, FIRST_HR_ORDERING,
PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED. This PR leaves every status unchanged.

## Verification

48 focused tests passed before publication, covering the ported fitter/path tests,
new postseason regressions, V3 pitcher accounting and common game readouts.
Tests include path-level team/player run conservation, empty-base postseason
extras, grand-slam and ordinary walk-offs, no third-out sacrifice run, explicit
unresolved-path failures, shared market identity, push conservation, invalid
probability rejection, and unsupported-market/role rejection.

Rules references:

- MLB postseason extras: https://www.mlb.com/news/mlb-extra-innings-rules-for-playoffs-2024-automatic-runners-and-pitch-clock
- MLB automatic runner: https://www.mlb.com/glossary/rules/designated-runner
- Official Baseball Rules 9.06(f)-(g), walk-off hit credit/home runs:
  https://content.mlb.com/documents/2/2/4/305750224/2019_Official_Baseball_Rules_FINAL_.pdf
