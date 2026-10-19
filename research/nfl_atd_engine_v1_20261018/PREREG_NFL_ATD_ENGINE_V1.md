# PREREGISTRATION — NFL anytime-TD engine v1: assessment + frozen validation plan

**Status: written BEFORE the engine is scored on any data. The sha256 of this file is
recorded in VALIDATION_RECORD.md and pinned in the scorer; the commit carrying this
file precedes every code commit on this branch.**
Written Sun 2026-10-18 (CT). Label of every output: RESEARCH_ONLY /
NOT_VALIDATED — an unvalidated estimate. The family stays REGISTERED_RESEARCH_ONLY,
eligible: false, promotable: false (config/nfl_family_registry_v2.json, `anytime_td`).
Nothing in this program produces a PLAY.

## 0. Assessment (why this family, and whether the data in hand supports it)

**Family:** `anytime_td` (blueprint N37) — the first of the 25 NFL prop families
registered research-only by PR #2265 / #2371 that gets an engine. Registration is
not an engine; before this branch the family was BLOCKED / NO_ENGINE on cards.

**Data in hand (verified 2026-10-18 before writing this plan):** the hash-pinned
nflverse weekly player-stats snapshot used by the Part 1/Part 2 props program —
`ps_2018..ps_2024.csv.gz`, `sp_2025.csv.gz`. SHA-256 of all eight files re-computed
and matched against `research/nfl_props_part2_20261018/SPEC_HASHES.txt` exactly
(15730d75…, d143b91c…, e23a81d6…, a2fb2665…, 2b7dca68…, b7590543…, 629b77e0…,
c7401e32…). Fields present per player-week: `rushing_tds`, `receiving_tds`,
`special_teams_tds`, `carries`, `targets`, `receptions`, `position`,
`position_group`, `player_id`, `player_display_name`. The priced quantity
(P ≥ 1 rushing or receiving TD) is fully observable in this data:
2020–2025 regular season holds 45,326 player-games, 6,634 (14.6%) with ≥ 1
rushing/receiving TD.

**Snap counts are NOT in the pinned snapshot.** The prior estimator
(`sportsedge/nfl_anytime_td.py`, NFL_ANYTIME_TD_NFLVERSE) fetched snap counts,
play-by-play and a games file live, outside any hash pin. This engine therefore
gates on **games played** (appearances in the weekly file — the same convention
the Part 1 preregistration declared: a player-week appears only if the player
recorded a stat, so zero-stat appearances are undercounted; that limitation is
accepted and declared, not hidden). Declared substitution, fail-closed: fewer
than MIN_GAMES prior appearances ⇒ UNPRICED, never a guessed price.

**Settlement gap, declared:** DraftKings settles fumble and special-teams TDs as
Yes (locked forward-test Rule 8). This engine prices rushing/receiving TDs only.
In 2020–2025 data, player-games whose only TD was a special-teams TD number 104
of 45,326 (0.23%) — a real but small class the engine does not predict; it is
reported descriptively in the results, never folded into the priced quantity.

**Prior record — preserved, not overwritten:** the earlier estimator's
calibration diagnostic is **FAILED_VALIDATION (diagnostic)**: 2023 walk-forward,
n = 4,760, Brier difference vs a naive baseline +0.0002 with 95% CI
[−0.0012, +0.0018] including zero; log-loss CI also included zero
(Oct 14 full-catalog program, carried Oct 17; source nfl_engine_audit_20261013).
That verdict belongs to that estimator (an opportunity-decomposition model on
unpinned live inputs). This engine is a **new version** under the version-scoring
rule: it is scored as specified here, from this point, and the earlier verdict
stays on the record untouched. A paired re-score of this engine against the
prior diagnostic on identical games is **NOT_EVALUABLE_FROM_RECORD**: the prior
diagnostic's per-row outputs are not preserved in the repository (its harness
depends on external worktrees — sportsedge-backtest / sportsedge-tdprops — and
the Oct 11 harness report stores aggregates only), so it is reported at verdict
level and **not reconstructed**.

**Assessment verdict: BUILD.** ATD can be priced honestly from the pinned data
with games-played gating. No generic league priors are used anywhere: the only
pool quantities are position-group rates computed from the same verified data,
point-in-time.

## 1. The engine (frozen construction)

For a player p and a game g, the engine estimates P(p scores ≥ 1 rushing or
receiving TD in g). Passing TDs never count for the thrower; a quarterback's
own rushing/receiving TDs do count.

- **Evidence games:** p's regular-season appearances in the weekly file with
  (season, week) strictly before g, drawn from g's season and the previous
  season, most recent first, capped at the **16 most recent**.
- **Recency weighting (declared a priori, fitted on nothing):** the i-th most
  recent prior game carries weight w_i = 0.5^(i / 8) — a role half-life of
  8 games. Weighted TD games T_w = Σ w_i·1[TD in game i]; weighted games
  N_w = Σ w_i.
- **Position pool:** pool rate for p's position group (QB / RB / WR / TE, from
  the `position` of p's most recent prior game) = (player-games with ≥ 1
  rush/rec TD) / (player-games) over all appearances of that group in strictly
  earlier weeks of g's season; if that count is < 200 player-games, the pool is
  the previous season's full-season rate for the group instead.
- **Shrinkage (declared constant, fitted on nothing):**
  model_p = (T_w + K_A · pool_rate) / (N_w + K_A), with **K_A = 10** weighted
  games of prior weight.
- **Gate (fail closed):** raw prior appearances < **MIN_GAMES = 4** ⇒
  UNPRICED_INSUFFICIENT_GAMES. A player whose position group is not one of
  QB/RB/WR/TE ⇒ UNPRICED_POSITION_GROUP_NOT_POOLED. An unresolvable name/id ⇒
  UNPRICED_NAME_UNRESOLVED. No other outcome is possible: every board row is
  either priced or UNPRICED with exactly one named reason.

## 2. Board pricing contract (mirrors the locked forward test)

The board pricer consumes rows {game_id, player_name and/or player_id, team,
yes_price (American), captured_at, kickoff} and emits, per row: model_p,
entry raw implied probability (cut included), **edge = model_p / raw implied − 1**
(descriptive only, locked Rule 9), and the selection **YES iff model_p > raw
implied, else PASS** (locked Rule 1), or **UNPRICED + reason** (locked Rule 2 —
unpriced rows join neither group). Rows that are not players (team D/ST rows,
"No Touchdown Scorer") are UNPRICED_NOT_A_PLAYER_ROW. Name matching normalizes
case, punctuation and generational suffixes (Jr./Sr./II/III/IV) and requires the
matched player's most recent team in the data to be one of the game's two
teams; anything else fails closed as UNPRICED_NAME_UNRESOLVED.

## 3. Calibration leg — frozen scoring plan (the only leg scored now)

- **Population:** every regular-season player-game in **2020–2025** whose player
  passes the §1 gate at that game (≥ 4 prior appearances, pooled position
  group). Probabilities are computed point-in-time from strictly earlier games
  only, exactly as §1 specifies. Outcome y = 1 iff rushing_tds + receiving_tds
  ≥ 1 in that game.
- **Baselines, on identical rows:** (a) **POOL** — the §1 position-pool rate
  itself (no individualization); (b) **RAW** — the player's unshrunk,
  unweighted TD rate over the same evidence games (T_raw / N_raw).
- **Metrics:** log loss (primary; probabilities clipped to [1e-6, 1−1e-6]) and
  Brier score (secondary; it was the prior diagnostic's headline metric and is
  reported for comparability, but no gate turns on it).
- **Uncertainty:** paired bootstrap, 2,000 resamples, resampling **games**
  (cluster key: season, week, unordered team pair), seed 20261018.
- **Verdict per baseline:** **BEATS_BASELINE** iff the 95% CI for
  Δ log loss (engine − baseline) lies entirely below 0; otherwise
  **DOES_NOT_BEAT_BASELINE**. Both baselines are reported separately; a split
  outcome is reported as a split outcome.
- **Descriptives (no gates):** calibration by predicted-probability decile;
  mean model_p vs realized rate; the count of ST-only TD player-games in the
  scored population.

## 4. Market leg — not evaluable historically

No historical DraftKings anytime-TD prices exist in free data, so the market
leg is **NOT_EVALUABLE_HISTORICAL** and no market baseline is fabricated. The
market verdict path is the **locked forward test**,
`docs/football/NFL_ANYTIME_TD_FORWARD_TEST_V1.md` (PR #2399, unmodified by this
program), starting Thu Oct 22, 2026 on captured boards priced by this engine:
status **PENDING_FORWARD_TEST**. Any demonstration on an already-captured board
is labeled HISTORICAL_DEMONSTRATION and is never prospective evidence (owner
provenance ruling, Oct 18).

## 5. Verification

Determinism (byte-identical rerun of the scorer), a hand check of ≥ 10 scored
player-games recomputed from the raw CSVs by code that does not import the
engine, and unit tests of the estimator arithmetic (shrinkage, implied
probability, Rule 1 boundary, Rule 9 edge).
