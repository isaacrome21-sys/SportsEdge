# SportsEdge Football — Build Spec to Production

**Target:** NFL + CFB, game-level markets validated on CLV, promoted through the existing four-stage ladder. Scope discipline is the point of this document.

**Status at last checkpoint:** infra ~7/10, validated predictive layer ~4-5/10. This spec closes the second number.

## 0. Reality check on “finish line”

There isn’t one. The realistic good outcome is:

- M2 beats M1 (market-based baseline) on log loss in walk-forward.
- Selected plays beat closing line by a measurable, statistically distinguishable margin.
- Truth Gate emits 0-4 official plays on a typical slate, and legitimately zero on many.

Anything promising more than that is a model that’s overfit and hasn’t found out yet. Build toward CLV, not toward a pick count.

## 1. KILL LIST — remove or freeze before adding anything

### 1.1 Delete outright

| Item | Why |
|---|---|
| ROI / units-won as any promotion criterion | Needs thousands of bets to reach significance. Football gives you hundreds per season. It will promote noise. |
| Any preseason-specific feature module (QB rotation model, snap-expectation model, coaching-tendency model) | ~48 games/season under the 3-game format, ~250 total since 2021. Not enough to fit or validate. Freeze the branch, do not delete the notes. |
| Player prop market support in v1 scope | Different data spine (usage → volume → efficiency). Does not ride the team-score simulator. Separate project. |
| Any duplicated NFL/CFB code path | Collapse to one core + two sport adapters. Duplicated paths drift and you’ll validate one and ship the other. |
| Hardcoded book/provider names in model or gate logic | Provider coupling belongs only in the odds adapter layer. |
| Any parlay / SGP / teaser logic currently present | Correlated-leg pricing is a separate problem. Out of v1. |

### 1.2 Audit and fix, do not delete

| Item | Action |
|---|---|
| M2 feature inputs | Grep every M2 feature for market data. Any line, total, implied prob, or book-derived value inside M2 is a leak. M2 must be blind to the market or the M0→M1→M2 separation is decorative. |
| Same-day leakage guard | Port the MLB fix. Any feature computed from a window that includes the game itself is a leak. Assert `feature_asof_ts < game_start_ts` at build time, not review time. |
| Coverage accounting | Verify it counts attempted events, not returned events. A provider silently dropping games should fail coverage, not pass at 100%. |
| The 262 tests | Count how many assert model correctness vs. plumbing. If it’s mostly plumbing (it usually is), that’s why infra is 7 and model is 4. |

### 1.3 Freeze

Preseason lane stays in SHADOW for the remainder of the 2026 preseason. Use it as a live-fire rehearsal of event binding, market discovery, no-vig, gate evaluation, and logging.

Expect and accept zero official plays. Do not tune anything based on it.

## 2. TARGET REPO STRUCTURE

```text
sportsedge/
  core/
    simulate/       # joint score distribution → all game-level markets
    novig/          # shared with MLB
    calibrate/      # isotonic + reliability, fold-safe
    walkforward/    # season-based splitter, no shuffle
    clv/            # decision-time and close-time logging + scoring
    gates/          # Truth Gate, promotion ladder
  sports/
    nfl/
      adapter.py    # implements SportAdapter
      features.py
      priors.py
    cfb/
      adapter.py
      features.py
      priors.py
  data/
    lines_history/  # NEW — see §3
    odds_live/      # provider failover, unchanged
  cards/
  tests/
```

### SportAdapter interface (write this first, everything hangs off it)

```python
class SportAdapter(Protocol):
    sport: str  # "nfl" | "cfb"
    def load_schedule(seasons) -> DataFrame: ...
    def load_lines_history(seasons) -> DataFrame: ...  # closing lines
    def build_features(asof_ts, games) -> DataFrame: ...  # MARKET-BLIND
    def margin_sigma(context) -> float: ...
    def total_sigma(context) -> float: ...
    def key_numbers() -> dict[int, float]: ...  # margin pmf mass
    def hfa_prior(venue, context) -> float: ...
```

If NFL and CFB both satisfy this, you get every downstream module once instead of twice.

## 3. DATA SPINE — build this before any modeling

You are blocked on live odds for card generation. You are NOT blocked on validation. Fix validation now with free historical data.

### 3.1 NFL history

`nflreadpy.load_schedules()` — `spread_line` and `total_line` back to 1999, moneylines from roughly 2006. Also carries rest days, roof, surface, temp, wind, coaches, `div_game`.

```python
import nflreadpy as nfl
sched = nfl.load_schedules(range(1999, 2027)).to_pandas()
pbp = nfl.load_pbp(range(2006, 2027)).to_pandas()
```

Verify first: does `game_type == "PRE"` carry non-null `spread_line` / `total_line`? If not, preseason calibration has no target variable and §1.1 is confirmed. 15-minute check.

Cache both to parquet. Never re-download in CI.

### 3.2 CFB history

CFBD REST API. Free tier is 1,000 calls/month, so bulk by season, never per game.

- `/games` — results, venue, neutral site, attendance
- `/lines` — closing lines from multiple books incl. consensus, back to ~2013
- `/plays` or `/ppa/games` — efficiency spine
- `/ratings/sp` and CORE ratings — priors
- `/player/returning` — returning production, critical for early-season CFB

One call per season per endpoint ≈ 60 calls to build the full history. Cache to parquet and treat the cache as the source of truth. Only hit the API for the current season.

Upgrade to a Patreon tier only when in-season polling volume demands it.

### 3.3 Line storage schema

```text
game_id, sport, season, week, book, market, side,
line, price, captured_ts, is_closing, source
```

Store the full path where available, not just close. You need open→close movement as a feature and close as the CLV target.

## 4. MODEL SPEC

### M0 — no-vig market benchmark

Convert market prices to fair probabilities. Shared with MLB, should need no work.

### M1 — market-based model

Input: current/closing line. Output: probabilities for every game-level market via the score simulator. This is the baseline M2 must beat. It should be hard to beat — that’s the point.

### M2 — independent model (the actual work)

Fit market-blind. Output: predicted margin, predicted total, and a covariance structure.

Simulate joint `(home_score, away_score)` → derive every game-level market from one distribution.

**Critical:** do not use a plain normal on margin for NFL. Key numbers 3 and 7 carry enormous probability mass. A smooth normal will systematically misprice every spread near 3. Use an empirical margin PMF, or a normal blended with a key-number point-mass mixture fit from history. CFB is flatter but 3 and 7 still matter.

Sigma starting points, refit from your own data:

- NFL margin σ ≈ 13.2-13.6
- CFB margin σ ≈ 16-17.5 (and heteroskedastic — grows with total)

### NFL feature set

- Opponent-adjusted EPA/play, offense and defense, pass and rush split
- QB adjustment — single largest factor. Explicit starter identity, not team-level.
- Pressure rate generated / allowed
- Success rate, explosive play rate
- Rest differential, travel distance, timezone crossings, short week, bye
- Roof, wind (dominant weather factor for totals — rain matters far less than wind)
- Early-season prior blend: prior-season adjusted efficiency decaying over weeks 1-6

### CFB feature set

- Opponent-adjusted PPA/EPA — mandatory. Raw efficiency in CFB is schedule-poisoned to the point of being actively misleading.
- Returning production (Connelly-style) — the highest-value early-season CFB feature
- SP+ and/or CORE as prior
- Success rate, explosiveness, finishing drives, havoc, line yards
- Portal/recruiting-adjusted talent prior for weeks 1-4
- Venue-specific HFA (CFB HFA varies far more than NFL — altitude, crowd, travel)
- Pace, for totals
- FCS opponent handling: flag and either exclude or model separately

The central CFB problem is the early-season prior. Weeks 1-4 have almost no current-season signal. Model this explicitly as a decaying prior weight, and validate the decay schedule by week rather than assuming one.

### Fitting

Regularized (ridge/elastic net) or GBM. Start regularized-linear — it’s harder to overfit and easier to diagnose.

Fit calibrator (isotonic) on training folds only. Never on test.

Report Brier and log loss vs M1 on every fold.

## 5. WALK-FORWARD PROTOCOL

Season-based folds only. Train ≤ season N, test season N+1, roll forward.

Never shuffle. Never use a random split.

- NFL: 2006-2025 → ~19 folds
- CFB: 2014-2025 → ~11 folds

Within-season, features must be as-of, not season-aggregate. This is where leakage hides. Assert it in code.

Report per-fold, not pooled. A model that wins on 6/19 folds and pools positive is a model that got lucky twice.

## 6. CLV HARNESS — the new Truth Gate criterion

### Why

Detecting a 3% ROI edge at -110 with 95% confidence takes roughly 4,000 bets. You will not have that in football for years. CLV converges in hundreds because you’re measuring against a much lower-variance target.

### Log at decision time

```text
decision_ts, game_id, sport, market, side, book,
line_at_decision, price_at_decision,
model_prob, novig_prob, ev, kelly_frac, stake_units,
gate_result  # OFFICIAL | REJECTED_<reason>
```

### Log at close

```text
game_id, market, side, closing_line, closing_price, closing_novig_prob
```

### Score

Measure CLV in **no-vig probability delta**, not line delta. Line delta breaks down across different prices and across markets with different line granularity.

```text
clv = closing_novig_prob(side) - novig_prob_at_decision(side)
```

Positive means the market moved toward your side after you bet it.

### Metrics

- Mean no-vig prob CLV per market
- % of plays beating close
- t-statistic on mean CLV
- Same metrics on rejected plays — if rejects have positive CLV too, your gate is the problem, not your model

### Gate thresholds (tune, but start here)

| Stage | Criterion |
|---|---|
| VALIDATED_MATH | Simulator reproduces known-closed-form results; no-vig round-trips; key-number mass matches empirical PMF within tolerance |
| PRODUCTION_LOGIC_PASS | M2 beats M1 on log loss in ≥ 65% of walk-forward folds, per market, per sport |
| CI_ATTESTED | Fixture attestation green; leakage assertions pass; calibration reliability max-bin deviation under threshold |
| DEPLOYED | n ≥ 200 logged plays in that market, mean no-vig CLV > 0, t > 2.0 |

Per market, per sport. NFL spreads passing does not promote CFB totals.

## 7. STAKING

- Fractional Kelly, quarter-Kelly cap.
- Hard per-market and per-slate exposure caps independent of Kelly.
- Kelly on a miscalibrated model is a fast way to lose. Cap first, size second.

## 8. SEQUENCED TASK LIST

Each task ships with its acceptance test. Feed these to ChatGPT one at a time — do not hand it the whole document and ask for a build.

### Week 1 — spine

1. Verify nflreadpy preseason line availability. **Accept:** documented yes/no in repo.
2. Write `SportAdapter` protocol + NFL and CFB stubs. **Accept:** both import, both raise `NotImplementedError` cleanly.
3. NFL lines-history ingestion → parquet. **Accept:** row count matches expected game count 1999-2025, null rate documented per column per era.
4. CFB lines-history ingestion → parquet, ≤ 100 API calls. **Accept:** same, 2013-2025.
5. Leakage assertion harness: assert `feature_asof_ts < game_start_ts` enforced in the feature builder. **Accept:** deliberately-leaked test fixture fails the build.

### Week 2 — core

6. Joint score simulator with key-number mixture. **Accept:** simulated margin PMF matches empirical NFL margin PMF; mass at 3 and 7 within tolerance.
7. Derive spread / ML / total / first-half / team-total from one simulation. **Accept:** internal consistency — ML prob from sim matches spread-at-0 prob.
8. Walk-forward splitter. **Accept:** no test-season row ever appears in a training fold; test fixture proves it.
9. Calibration module, fold-safe isotonic. **Accept:** fitting on test data raises.

### Week 3 — CLV + model

10. CLV logging both ends + scoring. **Accept:** replay a historical week end-to-end, produce a CLV report.
11. Rewrite Truth Gate to §6 thresholds. **Accept:** old ROI criterion removed, gate emits zero plays on a fixture where nothing qualifies.
12. CFB M2 v1: opponent-adjusted efficiency + returning production + SP+/CORE prior + venue HFA. **Accept:** walk-forward log loss vs M1 reported per fold, per market.

### Week 4 — NFL + ship

13. NFL M2 v1 with explicit QB adjustment. **Accept:** same reporting.
14. Prior-decay schedule validated by week for both sports. **Accept:** decay curve fit, not assumed.
15. Live odds key wired, DEPLOYED stage unblocked.
16. CFB Week 1 as first real promotion attempt. Expect few or zero official plays. That is a pass, not a failure.

## 9. PROMPTS FOR CHATGPT

Give it one task at a time with this frame:

> Repo: isaacrome21-sys/SportsEdge. Implement task N from `docs/FOOTBALL_ROADMAP.md`. Constraints: market data must never enter M2 features. All splits are season-based walk-forward, never shuffled. Calibrators fit on train folds only. Write the acceptance test first, show it failing, then implement until it passes. Do not modify the Truth Gate thresholds. Do not add new dependencies without asking.

The “write the failing test first” instruction matters more than anything else in that prompt. It’s what stops an agent from producing code that looks right and validates nothing — which is how you end up at 262 passing tests and an unvalidated model.

## 10. WHAT SUCCESS LOOKS LIKE IN NOVEMBER

- CFB spreads and totals: DEPLOYED, n > 200, mean CLV positive with t > 2
- NFL spreads and totals: DEPLOYED or CI_ATTESTED
- ML markets: probably still gated, because ML edges are harder and rarer
- Derivatives: riding the same simulator, promoted individually
- Preseason: still frozen
- Props: not started, correctly

That’s a good season. Anything substantially better than that means checking for a leak.
