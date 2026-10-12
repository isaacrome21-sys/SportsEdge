# SportsEdge backtest harness

The measurement foundation for Isaac's bar (2026-10-11):

> Every new factor must **prove** it improves **chronological out-of-sample**
> performance versus **both** the existing model **and** a market baseline
> before entering production pricing. No factor added on vibes.

All harness outputs are `research_only`. No betting authority, no staking.

## The bar, concretely

A candidate factor/model earns:

- **PASS** — beats the existing model out-of-sample on **both** Brier score
  and log-loss, on at least `min_n` predictions (default 30), **and** beats
  the market baseline where one exists.
- **CONDITIONAL_PASS** — beats the existing model, but no market baseline
  exists to check the second leg. This is **not** a full pass: do not
  promote a factor on this verdict alone.
- **FAIL** — any leg fails, with explicit reasons.

## The market-baseline limitation (read this)

Isaac does not use the Odds API, so there is **no complete historical market
baseline**. The harness handles this honestly:

- Where archived or manually recorded closing prices exist, pass them as
  `market_baseline` (dict keyed `(fixture_id, market, selection, line)` or a
  callable) and the baseline leg is checked for real.
- Everywhere else the baseline leg is flagged `MISSING` and the best
  achievable verdict is `CONDITIONAL_PASS`.

Market prices are **never invented**. A missing baseline is a documented gap,
not a zero.

## Evaluating a factor, step by step

1. **Collect historical fixtures** with `sportsedge.backtest.outcomes`:
   free sources only (ESPN scoreboard for NFL/CFB, MLB StatsAPI for MLB).
   ```python
   from sportsedge.backtest import outcomes
   events = outcomes.fetch_football_scoreboard(
       "nfl", dates="20240908", cache_dir="data/backtest")
   games = outcomes.parse_completed_football_games(events)
   ```
   Only FINAL games yield outcomes. Cache under a data dir so reruns never
   re-hit the network.

2. **Build fixtures** — one dict per game:
   `{"fixture_id", "kickoff", "as_of", ...}`. `as_of` is when the
   prediction is made and must be `<= kickoff`. Fixtures must be sorted by
   kickoff (the splitter raises on unsorted input rather than guessing).

3. **Split chronologically**:
   ```python
   from sportsedge.backtest import splits
   sp = list(splits.walk_forward_splits(fixtures, min_train=50,
                                        test_size=16, embargo_days=1))
   ```
   Every train fixture kicks off before every test fixture in its split.
   Fixtures sharing a kickoff are never divided across the boundary.

4. **Write a price adapter** — do not rewrite pricers; adapt them:
   ```python
   def price_fn(model_name, fixture, as_of, train):
       # existing: call the current production pricer restricted to `train`
       # candidate: current pricer + the candidate factor, same restriction
       ...
       return [{"market": "ML", "selection": "HOME", "model_p": 0.58}]
   ```
   The adapter receives `train` explicitly: the model may learn **only**
   from those fixtures. Anything else is lookahead and invalidates the run.

5. **Settle** with `outcomes.settle_game(game, market, selection, line)` —
   supports ML, SPREAD, TOTAL; pushes grade 0.5.

6. **Run and compare**:
   ```python
   from sportsedge.backtest import runner, report
   result = runner.run_backtest(fixtures=fixtures, splits=sp,
                                models=["existing", "candidate"],
                                price_fn=price_fn, settle_fn=settle_fn,
                                market_baseline=None)  # MISSING leg flagged
   comp = runner.compare_models(result)
   verdict = report.evaluate(candidate=comp["models"]["candidate"],
                             existing=comp["models"]["existing"],
                             baseline_status=comp["baseline"]["status"],
                             baseline=comp["baseline"]["summary"])
   print(report.to_markdown(verdict,
         candidate_records=result["records"]["candidate"]))
   ```

## Layout

- `splits.py` — `walk_forward_splits`, `fixed_split`; no-leakage invariants.
- `outcomes.py` — free-source outcome fetching + caching + `settle_game`.
- `metrics.py` — Brier, log-loss, calibration bins, hit-rate thresholds.
- `runner.py` — `run_backtest`, `compare_models`; baseline slot.
- `report.py` — `evaluate` (the bar), `to_markdown`, `to_json`.

## Tests

`tests/test_backtest_*.py`. Unit tests never touch the network: outcome
tests inject recorded fixtures from `tests/fixtures/backtest/`
(real ESPN NFL scoreboard responses, 2024-09-08/09/12, recorded once).
To re-record fixtures: fetch the same public endpoints and save the raw
JSON; the parser tests then run offline.

## Known limitations

- No complete historical market baseline exists (no Odds API by Isaac's
  choice); the baseline leg is conditional until archived prices exist.
- Outcome coverage today: NFL/CFB via ESPN scoreboard, MLB via StatsAPI.
  NBA and other sports are not wired.
- `settle_game` covers ML/SPREAD/TOTAL. Player-prop settlement needs
  per-player historical stat lines and is not yet implemented.
- Pushes grade 0.5 (half-win). This is a documented modeling choice.

## Market baseline leg (`market_baseline.py`)

Fills the runner's `market_baseline` slot with no-vig market-implied
probabilities. Sources, in composite precedence order
(`build_default_baseline`):

| # | Source | Coverage | Book policy |
|---|--------|----------|-------------|
| 1 | Keys-backed closing-line archive (PRIMARY, forward) | NFL/CFB/UFC; `archive/closing-lines/{sport_key}/{date}.ndjson` on the `data` branch, written by `closing-line-archive.yml` | DraftKings only (policy `books=[draftkings]`, US, american) |
| 2 | nflverse `games.csv` (CC-BY-4.0) | NFL 1999–present; documented closing consensus lines (PFR-sourced); moneylines + closing juice 2010+ | single consensus value, no per-book breakdown |
| 3 | ArnavSaraogi `mlb-odds-scraper` release `mlb_odds_dataset.json` (SBR-derived) | MLB 2021-04-01–2025-08-16; opening+closing, ML/spread/totals | DraftKings preferred, else median across books in decimal space |
| 4 | degenpredicts `data/nba/lines.csv` (compiler-aggregated) | NBA 2007-08 on, ML only (spreads/totals lack closing juice → MISSING by design) | aggregated close (SBR moneylines) |

Open datasets 2–4 are factual references only (no explicit license files
in sources 3–4; never redistributed). Recorded samples live under
`tests/fixtures/backtest/baseline/`; the full files are operator-provided
local paths (see `build_default_baseline`). Verified SHAs (2026-10-11):
`nfl_games.csv` 240fa910…, `nba_lines.csv` a4a53ba9…, `mlb_odds_dataset.json`
3f952fd0….

Fixture-id contract: `"sport:YYYY-MM-DD:away_full_name:home_full_name"`
with the **league-local (America/New_York) date** — build it with
`fixture_id_for_game()`. Spread/total baselines require the model's line
to exactly equal the archived closing point; anything else is MISSING.

### Market-blind boundary (read this — Isaac's standing rule)

Market data lives on the **evaluation side only**, unconditionally:

- Stored closes (the `data`-branch archive, local open-dataset files) are
  **research comparison context**. They are consumed through exactly one
  code path: `market_baseline.lookup()` → the runner's `market_baseline`
  slot → the baseline leg of Isaac's bar (did the candidate beat the
  market out-of-sample?).
- **No code path exists from stored closes into any pricing function.**
  Nothing under `sportsedge/` pricing modules imports
  `sportsedge.backtest` (verified); the phone runner
  (`artifacts/run_it_full.py`) never sees market data. Multi-book or
  sharp (e.g. Pinnacle) closes, where archived, sit **alongside** output
  as comparison context — they are never model features, never pricing
  inputs, never calibration targets for production pricing.
- `elo.py` is market-free by construction: ratings use only
  wins/losses/scores from the free outcome loaders.

Violating this boundary is a defect, not a feature request: any future
change that lets market prices flow toward pricing must be rejected in
review.

### Credit budget (keys-backed archive)

The Odds API free tier: 500 credits/month/key × 4 keys
(`SPORTSEDGE_ODDS_API_KEY[_2/_3/_4]`, Actions secrets, server-side only).
Closing-line capture costs regions(1) × markets(3: h2h,spreads,totals) ×
bookmakers(1: draftkings) = **3 credits per sport per paid pull**
(NFL+CFB = 6/run; the event index is free). `config/nfl_2026_provider_budget_v1.json`
holds a 76-credit NFL confirmation reserve; lower-priority paid work
(including this archive) may only run when remaining − cost ≥ reserve.
The historical endpoint (`/v4/historical/...`) is **unavailable on the
free plan** (provider returns `HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN`;
see `scripts/collect_mlb_the_odds_api_history.py`) — so the keys-backed
path is archive-forward only, and historical depth comes from the open
datasets above. `closing-line-archive.yml` is currently manual-dispatch;
scheduling it (e.g. a weekly post-slate dispatch ≈ 6 credits/week for
NFL+CFB in season) is Isaac's call.

## Elo comparison floor (`elo.py`)

Every model is compared against a transparent Elo floor
(`models=["existing", "candidate", "elo", "naive"]`; render floor rows
with `report.to_markdown(..., extra_models={"elo": ..., "naive": ...})`).
`make_elo_price_fn(sport, games_by_fixture_id)` returns a
runner-compatible price_fn for model `"elo"` (ML only); `naive_price_fn`
is the coin-flip floor (ML 0.5/0.5).

Parameters (documented starting values, **not tuned**):

| sport | K | HFA (Elo pts) | MOV | offseason carryover |
|-------|---|---------------|-----|---------------------|
| NFL | 20 | 65 | on (538-style) | 0.67 |
| CFB | 20 | 65 | on (538-style) | 0.50 |
| MLB | 5 | 25 | off | 0.60 |
| NBA | 20 | 100 | on (538-style) | 0.75 |

`expected_home = 1/(1+10^(-(elo_h+hfa-elo_a)/400))`;
`mov_mult = ln(|mov|+1)*2.2/(0.001*elo_diff+2.2)` (ties use 1);
offseason: `elo = 1500+(elo-1500)*carryover` on season change. New teams
start at 1500; updates are zero-sum. CBB is not wired (no CBB outcomes in
the harness; the code is sport-agnostic).

## Known limitations (updated)

- The keys-backed closing-line archive is currently EMPTY on the `data`
  branch (no captures dispatched yet) → its leg reports MISSING until
  `closing-line-archive.yml` runs. The nflverse/SBR/NBA open datasets
  populate the historical leg now.
- MLB is parked in the archive policy (zero scheduled paid captures);
  NBA is not in the archive policy at all → both rely on open datasets
  until Isaac changes the policy (budget math above).
- CFB has no evaluated open dataset → archive-forward only (MISSING today).
- Baseline spread/total legs require exact line matches and are sparse by
  design; NBA spread/total are MISSING (no closing juice in the source).
- Elo parameters are untuned starting values; the floor is deliberately
  simple.

## Actionability metric (pipeline health)

Isaac's headline number: on a typical board/run, what share of selections
actually reaches him as **actionable**? This metric measures the PIPELINE
(pricing coverage + quote freshness), not model skill. It needs no
harness-gating itself — it is not a model change — but it is the number to
watch grow: via correct pricing, broader market coverage, and fresher
quotes. The bar does not lower; the model gets smart enough to clear it.

Classification (see `report.summarize_actionability`):

| bucket | meaning | pipeline statuses |
|--------|---------|-------------------|
| actionable | priced with a current quote | `RESEARCH_CANDIDATE_NOT_VALIDATED`, `PRICED_RESEARCH`, `PRICED` |
| watch | priced but the quote is stale | `WATCH_*` |
| blocked | not priced | everything else, grouped by exact status/reason code |

Usage — pass the pipeline's evaluated rows
(e.g. `card["evaluated_rows"]` from the RUN IT pipeline):

```python
from sportsedge.backtest import report
summary = report.summarize_actionability(
    card["evaluated_rows"], run_id="2026-10-11-board-1",
    run_at="2026-10-11T19:00:00Z")
print(report.actionability_to_markdown(summary))
open("actionability_2026-10-11.json", "w").write(
    report.actionability_to_json(summary))
```

The summary is a JSON-serializable record
`{run_id, run_at, total, actionable:{n,pct}, watch:{n,pct},
blocked:{n,pct,by_reason:{code:n}}, research_only: True}` — store one per
run to track the actionable share over time. Append it to a factor report
with `report.to_markdown(verdict, actionability=summary)`.
