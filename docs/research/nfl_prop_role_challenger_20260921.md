# NFL prop role challenger — research only

**Authority:** `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`

This lane adapts the high-level workflow visible in the user-provided MySpariEdge prop examples: start from a player role/stat projection, stabilize recent usage against a projected role when history is sparse, apply matchup/game context to the appropriate football components, turn that into a probability distribution, and only then compare it with a paired sportsbook market.

It does **not** copy or claim any proprietary MySpariEdge formula, coefficient, weight, training set, score, or probability model. SportsEdge uses its own explicit research assumptions below. Nothing in this lane is promoted merely because the code exists.

## Supported prop families

The first challenger covers the ten families surfaced by the supplied examples:

- receptions
- receiving yards
- passing yards
- rushing yards
- rush attempts
- pass attempts
- completions
- pass TDs
- interceptions
- rushing + receiving yards

TD-scorer markets remain in their separate preplay-TD research lane. They are deliberately not mixed into this card.

## Architecture

The research flow is:

`projected role -> transparent shrinkage -> context -> shared player simulation -> prop distribution -> estimate_p -> paired DraftKings quote -> POWER_V1 no-vig -> EV`

### 1. Role stabilization

Each player supplies a `role_prior` and optional trailing observation. The current transparent shrinker is:

`stabilized = (prior_strength * role_prior + sample_size * trailing) / (prior_strength + sample_size)`

The default prior strength is 8 games and is an explicit research setting. It is not presented as a fitted optimum. With no usable trailing observation, the projected role is used directly. This keeps sparse/new-role cases from pretending a tiny historical sample is stable.

The role state contains:

- pass attempts
- completion rate
- passing yards per completion
- pass-TD rate per attempt
- interception rate per attempt
- rush attempts
- rushing yards per attempt
- targets
- catch rate
- receiving yards per reception

### 2. Context

Context is expressed as explicit multipliers, not a hidden checklist score:

- `volume_multiplier`
- `pass_multiplier`
- `rush_multiplier`
- `target_multiplier`
- `efficiency_multiplier`
- optional pass/rush/receiving efficiency multipliers
- `shared_workload_sigma`

Upstream adapters may derive those research inputs from matchup information such as opponent EPA, team total, PROE, injuries/depth chart, weather/wind, and game environment. This module does not invent weights for those sources. Market depth and cross-book agreement are diagnostics and must not be injected into `estimate_p` as probability boosts.

### 3. Shared simulation

One deterministic RNG stream creates coherent per-player draws. A shared workload latent variable links pass/rush/target opportunity. Counts are generated from workload; completions are conditional on pass attempts; receptions are conditional on targets; pass TDs and interceptions are conditional on pass attempts. Yardage is nonnegative and right-skewed using an explicit gamma-per-opportunity research assumption.

Hard invariants include:

- completions <= pass attempts
- receptions <= targets
- pass TDs <= pass attempts
- interceptions <= pass attempts
- all count/yard outputs are nonnegative integers
- `rush_receiving_yards == rushing_yards + receiving_yards` in every draw

Because every prop is read from the same draw set, combined-yard props preserve dependence rather than adding independently priced probabilities.

### 4. Prop probability and pushes

For every quoted threshold, simulation mass is divided into `over`, `under`, and `push`. Whole-number lines therefore preserve push probability. Half-number lines normally have zero push mass because the simulated statistics are integral.

The model-side field is `estimate_p`. `model_p` is intentionally absent. A research estimate cannot become Model_P without the separate prospective/PIT validation and promotion process.

### 5. Market contract

A prop is evaluated only when both OVER and UNDER quotes exist for the same:

- player
- prop family
- threshold
- DraftKings book

Both quotes require `retrieved_at` timestamps. Current controls are:

- quote TTL: 180 seconds
- maximum future clock skew: 30 seconds
- maximum paired-quote timestamp skew: 30 seconds

One-sided quotes are refused. Quotes from other books are not silently mixed with DraftKings.

No-vig probabilities use `POWER_V1`. When either side is longer than +400, the result is compared with proportional and additive de-vig alternatives. If the maximum method spread exceeds 1.0 percentage point, the market is refused as `DEVIG_METHOD_SENSITIVITY`.

With push mass, expected value per $1 risked is:

`EV = p_win * (decimal_odds - 1) - p_loss`

where `p_loss = 1 - p_win - p_push`.

Edge is measured against the market on the non-push conditional probability scale. Candidate ordering is economics-only: EV first, probability edge second, deterministic identity tie-breakers after that. There is no arbitrary score /100 and no narrative `why` field driving selection.

## CLI

```bash
python scripts/run_nfl_prop_research.py \
  --roles roles.json \
  --quotes quotes.json \
  --as-of 2026-09-21T18:00:00-05:00 \
  --sims 20000 \
  --seed 21
```

`roles.json` may be a list or `{ "players": [...] }`. `quotes.json` may be a list or `{ "quotes": [...] }`.

Example player skeleton:

```json
{
  "game_id": "2026-W3-AWAY-HOME",
  "player_id": "stable-player-id",
  "player_name": "Player Name",
  "team": "AWAY",
  "opponent": "HOME",
  "position": "QB",
  "sample_size": 5,
  "role_prior": {
    "pass_attempts": 34.0,
    "completion_rate": 0.65,
    "pass_yards_per_completion": 11.5,
    "pass_td_rate": 0.045,
    "interception_rate": 0.025,
    "rush_attempts": 4.0,
    "rush_yards_per_attempt": 4.2,
    "targets": 0.0,
    "catch_rate": 0.0,
    "receiving_yards_per_reception": 0.0
  },
  "trailing": {},
  "context": {
    "volume_multiplier": 1.0,
    "pass_multiplier": 1.0,
    "rush_multiplier": 1.0,
    "target_multiplier": 1.0,
    "efficiency_multiplier": 1.0
  }
}
```

Example quote pair:

```json
[
  {
    "player_id": "stable-player-id",
    "market": "completions",
    "side": "OVER",
    "line": 22.5,
    "price_american": -110,
    "book": "DraftKings",
    "retrieved_at": "2026-09-21T17:59:45-05:00"
  },
  {
    "player_id": "stable-player-id",
    "market": "completions",
    "side": "UNDER",
    "line": 22.5,
    "price_american": -110,
    "book": "DraftKings",
    "retrieved_at": "2026-09-21T17:59:45-05:00"
  }
]
```

## Promotion boundary

This is a challenger architecture, not a validated prediction model. Before any prop family can be called Model_P or feed an OFFICIAL card, that family must accumulate forward/PIT evidence under the existing SportsEdge governance requirements, including calibration, minimum promoted sample, CLV and after-vig performance requirements. No historical or forward evidence may be backfilled to manufacture eligibility.

**NOT Model_P / NOT Truth Gate / NOT OFFICIAL**
