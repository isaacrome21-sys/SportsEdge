# NFL Touchdown-Scorer Build — 2026-10-11

Branch: `feat/nfl-td-scorer-20261011`. Module: `sportsedge/nfl_anytime_td.py`.
Tests: `tests/test_nfl_anytime_td.py` (14/14 pass, offline).
Harness driver: `scripts/backtest_nfl_anytime_td.py`.
Full report: `docs/football/anytime_td_harness_report_20261011.md`.

## 1. Model design (anytime TD)

ETR opportunity-decomposition architecture, rebuilt on free data only:

```
team plays -> pass/run split (neutral script) -> player opportunity share
  -> red-zone split -> TD conversion -> P = 1 - exp(-xTD)
```

`xTD_i = ( x_rz_carries·c_rz_rush + x_open_carries·c_open_rush
         + x_rz_targets·c_rz_rec  + x_open_targets·c_open_rec ) × opp_factor`

- **Team plays**: trailing offensive plays/game (pass attempts + rush
  attempts on live plays), shrunk to the league mean (m = 8 games).
- **Pass/run split by game state**: neutral-script pass rate — 1st/2nd down,
  quarters 1–3, win probability 0.2–0.8 — trailing, shrunk to league mean.
  No spread/total conditioning: pricing stays market-blind.
- **Player opportunity share**: trailing carries / team rush attempts and
  trailing targets / team pass attempts, empirical-Bayes shrunk (m = 60
  opportunities) to PIT-safe position-group baselines. Player history is
  always required (≥5 prior games); the position baseline is a shrinkage
  target only, never a substitute.
- **Red-zone split**: trailing red-zone carry/target mix per player, shrunk
  (m = 20) to position baselines. Red zone = `yardline_100 <= 20`, live
  plays only (no penalties, kneels, spikes, 2PT).
- **TD conversion**: player TDs per opportunity, split red-zone vs open
  field, shrunk (m = 40) to PIT-safe position baselines.
- **Opponent factor**: opponent's trailing offensive TDs allowed vs league
  mean, multiplicative, clamped to [0.6, 1.6]. Documented approximation:
  one factor for all opportunity pools.
- **Poisson**: P(≥1 TD) = 1 − exp(−xTD), clipped to [1e-4, 1−1e-4].

### ETR component mapping (honest accounting)

| ETR component | Free-data implementation | Status |
|---|---|---|
| Team plays | Trailing plays/game, shrunk, opp factor | IMPLEMENTED |
| Pass/run split by game state | Neutral-script pass rate, trailing, shrunk | IMPLEMENTED |
| Routes × TPRR | **nflverse has no routes data.** Approximated by target share of team pass attempts × snap share (targets-per-snap role proxy) | APPROXIMATED |
| Carry share | Trailing carries / team rush atts, shrunk | IMPLEMENTED |
| Red-zone share | Trailing rz opps / team rz opps from pbp, shrunk | IMPLEMENTED |
| Goal-line personnel packages | No free personnel data; folded into rz opportunity mix | APPROXIMATED |
| TD conversion | Player TD/opp shrunk to PIT-safe position baselines, rz vs open | IMPLEMENTED |
| Game-state script beyond neutral rate | Would need spread/total (market-derived) | NOT WIRED |

## 2. Data sources (all free, no keys)

- `nflverse` `stats_player_week_{season}.csv` — per-game rushing/receiving
  TDs, carries, targets, receptions (player history). **This unblocks the
  Phase-7 `NO_VERIFIED_RUSH_RECEIVING_TD_HISTORY` classification** — the
  ESPN gamelog decoder was never extended; rushing/receiving TDs come from
  nflverse instead, as the task directed.
- `nflverse` `snap_counts_{season}.csv` — per-game `offense_pct`
  (participation gate ≥ 15%; name-join verified at 99.2% on eligible
  positions after suffix stripping).
- `nflverse` `play_by_play_{season}.csv.gz` (release tag `pbp`) —
  red-zone carries/targets/TDs, team rush/pass attempts, neutral pass
  rate, team offensive TDs. Required; fetch failure is fail-closed.
- `nflverse/nfldata` `games.csv` — kickoff timestamps; strict
  point-in-time filtering (every input row kickoff < priced kickoff).

All fetches carry sha256 source proofs; every priced prop's evidence block
records them.

## 3. Fail-closed reason codes

`TD_FETCH_FAILED`, `TD_SCHEMA_UNSUPPORTED`, `TD_IDENTITY_UNRESOLVED`,
`TD_IDENTITY_AMBIGUOUS`, `TD_HISTORY_INSUFFICIENT` (<5 games),
`TD_SNAP_SHARE_UNVERIFIED`, `TD_SNAP_SHARE_LOW` (<15%),
`TD_NO_TEAM_BASELINE`, `TD_TEAM_BASELINE_THIN`, `TD_POSITION_UNSUPPORTED`.

Uncertainty flags on every priced prop (sample-size based):
`TD_SAMPLE_SMALL` (<8 games), `TD_ROLE_UNCERTAIN` (snap <30%),
`TD_PRIOR_DOMINATED`, `TD_CONVERSION_PRIOR_DOMINATED`,
`TD_TEAM_BASELINE_THIN`.

## 4. First-TD scorer — stays blocked (correct outcome)

`assess_first_td()` returns BLOCKED /
`NO_VERIFIED_FIRST_SCORING_ATTRIBUTION`. Reasons: opening possession is a
game-time coin toss (random pre-kickoff; nflverse records the winner only
post-game); receive/defer tendencies don't overcome toss randomness to a
verifiable degree; the first TD is often not on the opening drive and
defensive/ST TDs can be first; per-player opening-drive TD samples are a
handful per season; no free source publishes pre-kickoff opening-drive
personnel/sequencing.

## 5. Harness verdict — CONDITIONAL_PASS (2026-10-11)

Walk-forward over completed 2026 regular-season games (weeks 1–5, 77 games,
6 splits), chronological out-of-sample, strict point-in-time (every input row
kickoff < priced kickoff). Paired comparison on the 955 player-games the
candidate priced:

| model | n | Brier | log loss | mean p | base rate |
|---|---|---|---|---|---|
| anytime-TD candidate | 955 | **0.1581** | **0.4987** | 0.156 | 0.213 |
| naive position baseline | 955 | 0.1663 | 0.5141 | 0.180 | 0.213 |

Brier Δ −0.0083, log-loss Δ −0.0154, n = 955 ≥ 30. Market baseline MISSING
(no Odds API by Isaac's choice) → CONDITIONAL_PASS, not full PASS: **do not
promote to production pricing on this verdict alone** (harness rule).

Honesty notes:
- The first run FAILED (Brier tie, log-loss +0.0012). Diagnosis found a real
  defect, not a tuning knob: team opportunity denominators were accumulated
  under the fixture team, misaligning ~24% of player-games for team-changers.
  The correctness fix (per-trailing-game team denominators) moved both
  metrics decisively. This is the harness working as designed.
- Calibration is monotonic but the candidate underpredicts at the low end
  (bin 0.0–0.1: mean p 0.066 vs hit 0.112). Refinement direction, not a
  ship-blocker for research use.
- Playable share: 955 priced / (955 + 311 blocked) = 0.754. Blocked by cause:
  TD_HISTORY_INSUFFICIENT 185, TD_SNAP_SHARE_LOW 119,
  TD_SNAP_SHARE_UNVERIFIED 7.

## 6. Per-market classification (coverage matrix)

| Market | Classification | Reason |
|---|---|---|
| NFL anytime TD | RESEARCH_PRICED (harness CONDITIONAL_PASS) | nflverse TD history + pbp opportunity model; beats naive position baseline out-of-sample on Brier and log-loss (n=955). NOT production-promoted: market-baseline leg missing per Isaac's bar |
| NFL first TD | BLOCKED_WITH_REASON | `NO_VERIFIED_FIRST_SCORING_ATTRIBUTION` |
| NFL 2+ TDs | NOT WIRED | Same xTD stream could price it (P(≥2) = 1−e^{−x}(1+x)); left unwired pending harness demand |
| CFB anytime TD | NOT WIRED | No free CFB equivalent of nflverse player_stats/pbp at this granularity |

## 7. Limitations

- Return TDs excluded from settlement (model prices offensive TDs only);
  ~2% of player TDs. Documented, not hidden.
- QB anytime TD = rushing/receiving TDs only (passing TDs never count for
  the scorer), per market spec.
- Snap-join misses (~0.8%) fail closed rather than guessing.
- Inactives: no pre-kickoff participation confirmation beyond trailing snap
  share; a surprise inactive is graded by the book (void), not the model.
- No market baseline exists (no Odds API) → best harness verdict is
  CONDITIONAL_PASS; do not promote on it alone.
- Shrinkage constants are documented a priori, not tuned; the harness
  decides whether they survive.
