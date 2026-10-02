# NFL attempt-9 shadow integration

Audited base: `78aae277890d5ef8b02d72e1cc075150d07b1867`.

Current main already carries the known-good attempt-9 runtime and Model_P
artifacts. The older open #743/#747 dependency chain is not an accurate inventory
of what has landed. The production `run_nfl_auto.py` still owns the M2 path; this
change adds a separate executable attempt-9 shadow path without transferring M2
promotion evidence or changing either frozen artifact.

## Execution

```sh
python -m scripts.run_nfl_attempt9_shadow \
  --schedule /absolute/path/to/acquired-nflverse-games.csv \
  --quotes /absolute/path/to/acquired-quotes.json \
  --out /absolute/path/to/new-shadow-report.json
```

The CLI uses the current clock and refuses to overwrite an existing report. The
schedule must be an acquired current snapshot. A historical reconstruction must
never be presented as a prospective capture. Report hashes bind the input bytes
and artifacts, but do not certify source acquisition or create promotion evidence.

The quotes file is a JSON list. Each record requires `game_id` (nflverse identity),
`market`, `line`, `selection`, `period: FULL_GAME`, `bookmaker: draftkings`,
`observed_at` (timezone-aware receipt), `kickoff_utc`, and exactly two `outcomes`.
Each outcome repeats `game_id`, `bookmaker`, `period`, and `observed_at`, and supplies
`selection`, `line`, and `american_odds`. Spread `line` is always the HOME handicap;
the away outcome carries its exact negative. Totals use the same line for both
outcomes. Receipt age must be between zero and 180 seconds. A source adapter must
establish the game mapping; the runner does not guess provider ID/name joins.

The report retains market-blind forecasts, prediction hashes, schedule hash,
canonical quote hash, frozen artifact hashes, every submitted quote disposition,
and every market in `football_market_surface.json`. Positive model edge is not
permission to bet. The canonical `decide_bet` executes with the artifact's actual
`deployed=false`; Kelly and stake are zero. The 3% necessary policy floor used in
this diagnostic does not substitute for a provenance-verified production floor.

## Implementation provenance and fixes

The raw prediction producer and its two baseline regressions are ported from
`39bbba888bb1746a6606d919c47db1eef19487cb` (#743). This port adds digest verification
for existing predictions, kickoff identity checks, atomic non-overwriting writes,
duplicate/unsafe game-ID rejection, finite runtime validation, future-score
rejection, and single-read schedule hashing. Same-day results are excluded to
preserve the frozen builder's date-batched feature semantics. No frozen code
binding or evidence registry is rewritten. This modified producer is not the
older frozen producer and is not activated for confirmation evidence.

## Remaining completion blockers

| Market/engine | Current attempt-9 support | Required next evidence/work |
|---|---|---|
| Full-game and alternate spread/total | Non-integer shadow probabilities | Artifact-bound prospective evidence and deployment |
| Integer spreads/totals | Explicitly blocked | Independently validated discrete push mass |
| Moneyline | Unsupported by attempt-9 v1 | Validated tie/score distribution |
| Team totals | Separate research pricing code exists | Validated joint score model and derivative-specific promotion |
| Halves, quarters, situational | Unsupported by attempt-9 | Validated sport/period-specific distributions |
| Player, kicker, defender props | Runtime registry remains NO_ENGINE | G1 independent validation, PIT inactive status, forward evidence, certification |

The frozen 2026 prospective policy requires at least 200 promoted decisions and
12 distinct week clusters, plus calibration, CLV, ROI, exact identity, CI and
Truth Gate floor provenance. It cannot be satisfied by this implementation or
synthetic tests. The V2K admission permits research implementation only; its
development-validation execution flag is false and attempts remain 0/5. The G1
prop ledger also remains unspent. Those recorded gates must be completed before
evaluation/promotion; this PR does not consume attempts or relax any threshold.

No main bypass, evidence backfill, confirmation-capture modification, paid-provider
spend, market activation, or OFFICIAL/staking authority is introduced.

## Verification

61 focused unittest cases passed locally, including unchanged frozen artifact/code
bindings and existing NFL readiness/run-machine tests. At
`2026-09-20T04:55:25Z`, a current nflverse schedule snapshot produced 31 future-game
raw forecasts with zero blocked games and all 51 market dispositions. Snapshot
SHA256: `15d5996120ef2b52e734fc5a0215dff16d8e4d89dece74337cf08b29ddd7f361`.
No live quotes were available: the existing direct-DK preflight returned
`DIRECT_DK_UNAVAILABLE / DK_DIRECT_BOARD_UNAVAILABLE`. Therefore no live-priced
card or forward evidence was produced. Fixture pricing tests are synthetic
contract checks, never live evidence.
