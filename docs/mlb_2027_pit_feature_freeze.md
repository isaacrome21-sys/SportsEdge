# MLB 2027 candidate lane — PIT feature eligibility and leakage freeze

Status: **FROZEN RESEARCH SPECIFICATION**

**NOT Model_P · NOT Truth Gate · NOT OFFICIAL**

Scope: the single 2027 MLB candidate lane frozen in `docs/mlb_2027_candidate_lane_freeze.md`, producing one coherent full-game run distribution for moneyline, run line, and full-game total.

## Point-in-time rule

For a prediction with decision timestamp `T`, every feature value must be reproducible using only information whose source publication/observation timestamp is at or before `T`. Event dates alone are insufficient. If availability at `T` cannot be established, the value is **MISSING** and the governed path fails closed.

No feature may be reconstructed from a later snapshot and treated as if it were known earlier.

## Eligible feature families

Only PIT-safe versions of these families may enter the candidate lane:

- starter identity and handedness;
- starter performance and workload history from games completed before `T`;
- confirmed lineup/order information published at or before `T`;
- batter performance history from games completed before `T`;
- bullpen availability/workload derived only from games completed before `T`;
- park/venue characteristics whose effective version was known at `T`;
- weather observations/forecasts captured at or before `T`;
- schedule/rest/travel variables derivable from the schedule known at `T`;
- season-to-date and rolling team/player statistics calculated strictly from prior games.

A source being public does not make it PIT-safe. Source lineage and as-of time are required.

## Explicitly prohibited leakage

The governed lane must not use:

- final score, inning, play-by-play, or box-score information from the target game;
- target-game outcomes embedded in season-to-date or rolling aggregates;
- revised/corrected statistics first published after `T` unless the version known at `T` is preserved;
- closing odds, future line movement, or post-decision market information as model features;
- lineups, scratches, starter changes, weather, or injury/status updates first known after `T`;
- end-of-season ratings, standings, awards, projections, or retrospective labels that include future games;
- random train/test rows that allow later games to inform earlier-game feature construction;
- any imputed value whose computation uses future observations.

Market prices may be used only where the frozen lane explicitly requires observed market quotes for pricing/evaluation; they may not silently enter the predictive feature set.

## Rolling and aggregate construction

For target game `g` at timestamp `T`:

1. Sort source events by their actual observation/publication time.
2. Restrict the source set to observations available at or before `T`.
3. Exclude `g` and every later event.
4. Compute rolling/expanding statistics from that restricted set only.
5. Preserve the exact source identifiers, source timestamps, and transformation version used.

Minimum-sample behavior must be deterministic and frozen. A missing history must not be replaced with a retrospectively computed league/player value unless that fallback itself is PIT-safe and predeclared.

## Starter, lineup, bullpen, park, and weather semantics

Starter features require a starter identity known at `T`; otherwise starter-dependent readiness is MISSING.

Lineup/order features require a lineup snapshot captured/published at or before `T`. A final lineup obtained later cannot backfill an earlier decision.

Bullpen workload may include only appearances completed before `T`; target-game usage and later corrections are excluded.

Park features must be versioned by effective date. Retrospective full-season park factors are not eligible for earlier predictions unless constructed PIT from prior games only.

Weather must carry the forecast/observation issue time. Historical realized game weather cannot substitute for a pregame forecast when evaluating what was knowable at `T`.

## Training, calibration, and validation isolation

Feature construction must occur PIT before partition use.

- Training data may fit model parameters.
- Frozen calibration data may fit only the predeclared calibration step.
- Validation/holdout data may evaluate only.
- Replay holdout must never drive feature selection, hyperparameter tuning, thresholds, transforms, missingness rules, or calibration choices.
- A failed validation result cannot be repaired by tuning against that same holdout.

Historical market replay remains prohibited unless a source passes the separate frozen replay audit for per-quote timestamp, same-book two-sided pricing, and true closing-price provenance. Current status remains forward-capture by default.

## Missingness and fail-closed behavior

Missing is **MISSING**, not evidence.

Required inputs absent at the decision timestamp must produce an explicit readiness failure. Do not infer an opposite-side price, fabricate a timestamp, use a later snapshot, or silently substitute a retrospective value.

The later readiness specification may define which optional features can be absent, but it may not weaken these PIT/leakage rules.

## Reproducibility contract

Each generated training or prediction snapshot must ultimately record enough lineage to reproduce:

- game identifier;
- decision/as-of timestamp;
- source identifier(s);
- source observation/publication timestamp(s);
- feature/transformation version;
- model-input values, including explicit MISSING values;
- partition membership.

Any feature that cannot satisfy this contract is ineligible for the governed lane until its provenance is repaired.

## Freeze rule

Changes to this specification after governed data collection begins require a new version and prospective evaluation. They may not be applied retroactively to improve replay/holdout results.

Props and period markets remain out of scope and blocked until at least one of moneyline, run line, or full-game total passes the governed path.
