# Elo team-strength foundation — integration guide

**Status:** research-only, harness-gated. The Elo rating replaces the opaque
`margin_proxy` as the team-strength input to score means. Do NOT rewrite
`artifacts/free_models.py` or `sportsedge/team_half_pricing.py` in this
branch — those modules live in PR branches. This package is designed to be
merged under them and wired in with the small adapters below.

## What the package is

`sportsedge/ratings/` — per-sport Elo (NFL/CFB/NBA/MLB), opponent-adjusted,
updated after each game on pre-game info + opponent quality only.

| Module | Contents |
|---|---|
| `params.py` | Every parameter with `value`, `source`, `status`. Run `params.audit_table()` for the full audit. |
| `elo.py` | `EloTracker`: chronological ratings; no-lookahead enforced structurally (non-decreasing dates, `rating_at` uses `date < as_of`). |
| `layers.py` | Declared adjustment layers: `hfa_layer` (DECLARED_LEGACY), `rest_layer` / `travel_layer` (interface declared, NOT_WIRED — Phase 2). `build_means()` assembles means + factor-coverage audit. |
| `provider.py` | `RatingProvider`, canonical `get_team_strength(team, as_of, sport)`, JSON store load/save, module-level `configure()`. |
| `history.py` | `GameRecord` (verified completed game), `season_label()`. |

## Data flow

```
free endpoints (ESPN scoreboard / MLB StatsAPI)
        │  scripts/refresh_ratings.py  (offline data-side job; Isaac runs nothing)
        ▼
data/ratings/{nfl,cfb,nba,mlb}.json   (persisted EloTracker state)
        │  RatingProvider.load() + configure(sport, provider)  (runner startup)
        ▼
get_team_strength(team, as_of, sport) -> TeamStrength
        │  .strength_points  (neutral-site, points above average)
        ▼
layers.build_means(base_mean, home_strength_pts, away_strength_pts, layers=[...])
        │  -> home_mean, away_mean, factor_audit (used vs missing per layer)
        ▼
model_probability(sport, market, side, line, home_mean, away_mean)
```

Fail-closed: unknown team → `RatingError(UNRATED_TEAM)` → pricing BLOCKS.
Unconfigured sport → `RatingError(PROVIDER_UNCONFIGURED)` → pricing BLOCKS.
The rating never silently defaults to 1500 in production.

## Adapter 1 — team_half_pricing mean construction

Current code (team-half branch) builds means inline:

```python
def margin_proxy(hist):
    if len(hist) < 3:
        return 0.0
    diffs = [own - opp for _, own, opp in hist]
    return max(-4.0, min(4.0, sum(diffs) / len(diffs) * 0.15))
home_rating = margin_proxy(home_hist)
away_rating = margin_proxy(away_hist)
home_mean = base + hfa / 2 + home_rating
away_mean = base - hfa / 2 + away_rating
```

Replace with (after `configure()` at runner startup):

```python
from sportsedge.ratings import get_team_strength, RatingError
from sportsedge.ratings.layers import build_means

try:
    home_s = get_team_strength(home, kickoff, sport)
    away_s = get_team_strength(away, kickoff, sport)
except RatingError as exc:
    return {"status": "NO_MODEL_OR_MARKET",
            "reason": "TEAM_STRENGTH_UNVERIFIED:" + str(exc), ...}

built = build_means(sport, base_mean=base,
                    home_strength_pts=home_s.strength_points,
                    away_strength_pts=away_s.strength_points)
home_mean, away_mean = built["home_mean"], built["away_mean"]
factor_audit = built["factor_audit"]   # attach to the card
```

Notes:
* `kickoff` as `as_of` means the rating reflects games strictly before
  kickoff — no lookahead, matching the `schedule()` history semantics.
* The factor audit (`league_prior`, `team_strength_elo`,
  `home_field_advantage`, `rest_differential`, `travel`) goes on the card
  so every price shows which layers were used vs NOT_WIRED.
* Keep the existing `IMPLAUSIBLE_SCORE_MEAN` guard unchanged.
* Do NOT remove the margin_proxy code in the same commit — keep it behind
  a flag until the harness verdict for that sport is at least
  CONDITIONAL_PASS (see validation results below).

## Adapter 2 — free_models.calculate context ratings

`context_for()` currently sets `home_rating`/`away_rating` from
`avg margin × 0.12` capped. The Elo strength is a drop-in for those two
context keys:

```python
from sportsedge.ratings import get_team_strength, RatingError

# inside context_for, per prefix/name:
try:
    strength = get_team_strength(name, kickoff, sport)
    out[f"{prefix}_rating"] = round(strength.strength_points, 3)
    notes.append(prefix.upper() + "_RATING_ELO:"
                 + f"{strength.rating:.1f}/{strength.rating_games}g")
except RatingError:
    notes.append(prefix.upper() + "_RATING_UNVERIFIED")
    # leave out[f"{prefix}_rating"] at 0.0 and let downstream decide:
    # production must treat UNVERIFIED rating as BLOCKED, not as average.
```

Downstream, `calculate()` must check the notes: if either side's rating is
`UNVERIFIED`, return `BLOCKED_CONTEXT_UNVERIFIED` rather than pricing with
a zero strength (a zero is a claim of averageness — do not invent it).

The rest of `calculate()` is untouched: injury/form/pitcher/weather context
keys keep working, and the market-anchor logic is orthogonal.

## Adapter 3 — NBA rest (example of a future Phase 2 layer)

When Phase 2 declares a rest coefficient, only `layers.py` changes:

```python
def rest_layer(sport, *, home_rest_days=None, away_rest_days=None):
    ...
    status="DECLARED_UNVALIDATED",  # was NOT_WIRED
```

`build_means()` picks it up automatically; the audit flips from
`layers_not_wired` to a real adjustment. No caller changes.

## Harness validation (Oct 11, 2026)

`scripts/validate_vs_margin_proxy.py` — walk-forward, per sport, both
models restricted to train-only history, settled on verified scores from
free endpoints (ESPN scoreboard day pages for NFL/CFB/NBA — note ESPN now
ignores the legacy `?season=&week=` params, so history is collected per
day; MLB StatsAPI monthly schedules). Markets: ML + SPREAD@0 +
TOTAL@league-mean, via `model_probability`. Existing model is
team_half_pricing's exact margin_proxy (differentials x 0.15, cap +/-4,
min 3 games).

| Sport | Games | Verdict | Elo Brier / log-loss | Proxy Brier / log-loss | n preds |
|---|---|---|---|---|---|
| NFL | 894 | CONDITIONAL_PASS | 0.2270 / 0.6516 | 0.2409 / 0.6804 | 1800 |
| CFB | 3250 | CONDITIONAL_PASS | 0.2298 / 0.6550 | 0.2320 / 0.6595 | 6033 |
| NBA | 2466 | CONDITIONAL_PASS | 0.2353 / 0.6682 | 0.2417 / 0.6794 | 3609 |
| MLB | 9794 | **FAIL — does not ship** | 0.2530 / 0.7007 | 0.2498 / 0.6928 | 10803 |

Market-baseline leg: MISSING everywhere (no Odds API by Isaac's choice) —
best achievable verdict is CONDITIONAL_PASS per the harness spec. Do not
promote on a conditional verdict alone; the market leg needs archived
closing prices before any production wiring.

MLB note: the Elo candidate loses to the simple margin proxy on both
metrics. The rating does NOT ship for MLB means. Hypotheses (not tested):
K=8 adapts too slowly for the proxy's recency edge, or elo_per_point=90
mis-scales run differentials. Any retuning must be a separate
walk-forward exercise — not tuned on this test set.

## Limitations (honest)

1. `elo_per_point` scalings and K-factors are DECLARED, not fitted. The
   harness judges them as a bundle; per-parameter tuning is future work
   and must itself be walk-forward validated.
2. CFB ratings mix 130+ teams with sparse cross-play; early-season ratings
   carry the 1500 prior (visible via `rating_games` in the audit).
3. The rating is matchup-blind by design (team quality only). QB/pitcher
   participation adjustments are separate Phase 2 layers — a missing
   critical layer must BLOCK or downgrade, never silently price
   (Lamar-out / Skubal-Misiorowski lesson).
4. Rest/travel layers are NOT_WIRED interfaces; `build_means` reports them
   in `layers_not_wired` on every card.
5. Ratings update on final scores only — no in-game/live updating (live
   phase owns that).
