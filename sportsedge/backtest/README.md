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
