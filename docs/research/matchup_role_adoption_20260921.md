# Matchup and role research adoption — 2026-09-21

## What was actually observed

The user authorized inspecting their MySpariEdge subscription and adapting useful
ideas. These are summaries of the visible methodology, not copied code, fitted
weights, a verified track record, or a claim to reproduce that product.

| Source reviewed | Disclosed mechanism | SportsEdge adaptation |
| --- | --- | --- |
| [NRFI/YRFI methodology](https://www.myspariedge.com/models/mlb/nrfi) | Starter strikeout-based hold probability; capped/shrunk first-inning history; stabilized opposing top-three OBP; run environment; complementary outcomes | Explicit-parameter matchup challenger, source/input hashes, confirmed starter/lineup and pregame checks; average conditional products over shared environment scenarios |
| [TD methodology](https://www.myspariedge.com/models/nfl/anytime-touchdowns) | Rushing/receiving scorer definition, goal-line carries, close-range targets, role ceilings and recent-role fallbacks | Separate preplay rush/target zone roles; small-sample team-share stabilization; existing shared paths produce 1+/2+/3+ offensive TD probabilities and joint scorer events |
| [Props methodology](https://www.myspariedge.com/models/nfl/player-props-edge) | Historical call-shape calibration; projections versus real thresholds; score differs from probability; raw-price edge differs from no-vig comparison | Shared win/loss/push price arithmetic with explicit conditional fair price and unconditional EV; stale/started quotes cannot produce value output |
| [General methodology](https://www.myspariedge.com/learn/how-our-models-work) | Stats, roles, conditions, quality/opportunity, confirmation and immutable grading; exact formulas and weights withheld | Independently implemented ideas only; no external percentage renamed SportsEdge Model_P |

The TD board describes independent parlay multiplication. We do not adopt it.
The general methodology's confidence-tier language also differs from the props
page, which explicitly disclaims confidence grades. Neither provides evidence
that a high display score is calibrated probability or profitable value.

## Concrete existing limitations addressed

`v7_distribution.first_inning_probabilities` uses a constant share of full-game
runs and a negative-binomial marginal. This challenger supplies a separate
pitcher/top-order feature route. It is not registered as its replacement.

The current Engine B allocator sets red-zone status using either yardline <=20
or an already-known touchdown outcome. That makes long touchdowns use red-zone
weights. The research allocator determines role strictly from preplay yardline,
with rush zones <=5/<=20 and target zones <=10/<=20. Outside these zones it uses
ordinary usage. Zone shares replace rather than multiply ordinary shares.
Existing active/route candidate conditioning and fallback behavior are retained
and remain limitations to assess. These zone boundaries are transparent research
choices, not coefficients inferred from MySpariEdge or validated improvements.

## Execution

`python scripts/run_matchup_research.py nrfi input.json` accepts the keyword
schema of `predict_first_inning`: pitcher and batter dataclass objects encoded as
JSON, explicit `parameters`, `(weight, run_factor)` scenario pairs, source hash,
game identity, confirmation booleans and ISO timestamps. All coefficients and
prior strengths are required; no fitted artifact or forecast is fabricated when
they are missing. `training_end` and source timestamps are caller attestations,
not automatic proof of historical PIT lineage. A formal fit needs a separately
approved/frozen dataset and evaluation policy. No fit or historical evaluation
was performed in this change.

`python scripts/run_matchup_research.py td input.json` takes `home_usage` and
`away_usage` in the existing TeamUsageProfile schema, all-player `roles` with
the four ZoneRole shares, an explicit RNG `seed`, existing Engine A `paths`, and
`player_ids`. It attributes those paths and reports scorer marginals and the
all-selected-score joint probability. Feed only independently sourced pregame
role estimates. This research interface does not establish their PIT provenance.
It does not generate missing paths, defense/return scorer identities, or overtime.
Its scope is explicitly **OFFENSIVE_REGULATION_ONLY**, not book-complete ATTD.

`python scripts/run_matchup_research.py price input.json` takes `win`, `push`,
`american_odds`, `quote_at`, `now`, `start`, and `ttl_seconds`. The probability
and quote must already refer to the exact same market, line, side, player and
settlement rules; this arithmetic helper is not a market-identity validator.
It serves binary or threshold markets with ordinary win/loss/push settlement,
not dead-heats, quarter-line split stakes, or arbitrary multi-leg payouts.
No-vig edge stays null: same-book pairing and frozen devig remain upstream.

## Coverage and outstanding work

### RUN IT: strongest positive-EV lines first

The requested default presentation is a short scored card, not a wall of
eligibility labels. Run:

```sh
python scripts/run_matchup_research.py board lines.json --format markdown
```

It displays up to five highest-scoring, current positive-EV candidates scoring
at least 60/100. Multiple books quoting the identical contract produce one
display selection at the best available scored price. Nothing qualifying means
an empty card, not a forced recommendation. These are individually ranked lines,
not a portfolio or parlay; correlation and stake sizing are not inferred.
`--limit`, `--min-score` and `--all-lines` control the display. JSON retains every
submitted row and its explanation, including missing models and rejected inputs.

The score is **70 × clip(EV / 0.30, 0, 1) + 30 × P(win | no push)**, rounded to
one decimal. These are disclosed display weights, not learned coefficients.
60 is a UI cutoff, not evidence of predictive accuracy. Model win probability
and expected profit per unit remain separate. Positive EV is conditional on the
supplied model being right; this PR does not establish calibration or profitability.
No external percentage is renamed as an internally validated probability.

Input is an object with `rows`, optional `now` (otherwise current UTC), and
optional `quote_ttl_seconds`/`estimate_ttl_seconds` (defaults 300/900). A row has:

- `quote`: `quote_id`, `book`, `contract`, `american_odds`, `quote_at`, `start`.
- Optional `estimate`: `contract`, unconditional `win` and `push`, `model_id`,
  `model_version`, `artifact_sha256`, `features_as_of`, `generated_at`, `valid_until`.
- Both contracts must exactly agree on `sport`, `event_id`, `market`, `selection`,
  nullable `entity_id` and `line`, `period`, `rules_id`, and `payout_type`.
  The only supported payout type is `WIN_LOSS_PUSH`. Explicit rules and period
  prevent offensive-regulation TDs from being matched to book-complete ATTD.

All timestamps require offsets. Expired, future, started, missing-source and
mismatched estimates cannot score. Refreshing an estimate timestamp cannot revive
an old feature snapshot. Artifact identity is caller-attested, not verified by
this renderer. Probability estimation, live data acquisition, screenshot/text
parsing and market-specific adapters remain upstream; quotes alone cannot produce
probabilities. This opt-in command is not a replacement for the production runner.

`examples/research_scored_board_synthetic.json` is an executable **synthetic**
example at a fixed historical time, not a current betting line:

```sh
python scripts/run_matchup_research.py board examples/research_scored_board_synthetic.json --format markdown
```

### PR #895 reconciliation repair

The three initial failing checks shared one repository assertion: main's governed
content no longer matched checkpoint `2dcd200a244a959c04c972ed652c5142804a6b18`.
The registry now records all 32 intervening first-parent commits through
`78aae277890d5ef8b02d72e1cc075150d07b1867`. Entries use actual git SHAs; `pr: 0`
means the commit subject did not identify a PR. No PR identity was guessed.

Before advancing the checkpoint, the effective coverage audit replayed all 736
delta/bundle rows: 47 confirmed drift, 689 not applicable, zero unresolved rows.
All drift dispositions remain terminal under the existing policy; no disposition,
selector, authority, test or hold was relaxed. Effective governed-surface SHA-256:
`fb1945e2c003e6e1890e7c93aa026bcec9033a080230ad00a8552b2055e75f40`.
The registry still declares inventory incomplete and reconciliation still reports
`ACTIVE_FREEZE_BUNDLE_INVENTORY_INCOMPLETE`; this change does not claim release authority.
Reproduce with `scripts/build_reconciliation_registry_view.py` followed by
`scripts/reconcile_freeze_deltas.py --registry <effective-registry> --current-main-ref origin/main`.

| Family | What this change delivers | Still required |
| --- | --- | --- |
| NRFI/YRFI | Executable matchup candidate and shared-environment mixture | PIT feature adapter, fitted coefficient artifact, untouched evaluation, official evidence |
| Offensive TDs | Executable preplay allocation and 1+/2+/3+/joint readouts | Fitted PIT role shares; integrate complete scorer, returns/defense/OT, book void rules |
| Football yards/volume | Same attributed paths remain compatible with existing player-stat readouts | End-to-end live runner integration and per-market calibration |
| Other binary/threshold markets | Reusable price arithmetic | Their own valid distribution, live quote identity and validation; no new engine claim |
| MLB HR/hits/pitcher props, CFB, period/first/last markets | Methodology audit only in this increment | Existing respective engine/data/evidence work; not completed by this PR |

Do not adopt an arbitrary 90-minute lock or reopen historical snapshots. Existing
sport-specific capture policies, attempt budgets, no-backfill boundaries, main
protection and closed MLB evidence remain unchanged. All code is explicit opt-in
research; no Model_P authority, Truth Gate pass, eligibility, staking, promotion
or production activation is created. Synthetic tests are not predictive evidence.

## Validation

Focused `unittest` checks cover complementary first-inning mass, home/away matchup
identity, shrinkage, PIT/confirmation rejection, hash binding, shared-environment
dependence, preplay TD allocation, separate rush/target roles, reconciliation,
joint TD probability versus an incorrect product, stale prices and pushes.
Existing Engine B and player-market suites are also run.

Local validation uses Python 3.12.14 / NumPy 2.3.5; the repository's exact contract
is Python 3.12.13 with the dependencies in `requirements-test.txt`. Local results
are engineering checks, not a claim to have satisfied that hosted CI gate.

After the #895 repair, `python -m pytest -q tests` passed 3,198 tests and 770
subtests locally. Thirteen scored-board tests cover value arithmetic, no filler
picks, price ranking/deduplication, exact settlement identity, stale/future data,
source requirements, pushes, market coverage, and the executable Markdown card.
