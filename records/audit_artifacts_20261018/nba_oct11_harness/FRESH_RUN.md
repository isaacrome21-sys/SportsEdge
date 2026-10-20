# Fresh NBA harness run — unique-game scoring (per RECEIPT.md / issue #2410)

**Date:** Tue Oct 20, 2026 · **Type:** NEW evaluation from the committed
outcome cache — not a re-score of the Oct 11 run (whose per-game predictions
were never persisted; see `RESULT.md` in this directory).

## Inputs and verification

- Source: branch `records/audit-artifacts-20261018` @ `3a5ed3069`,
  `records/audit_artifacts_20261018/nba_oct11_harness/` (RECEIPT.md followed).
- **Manifest verification: PASS — all 43 cache files decoded
  (`base64 -d | gunzip`) match `MANIFEST.sha256` exactly (43/43 OK).**
- The harness reads `~/workspace/sportsedge-nba/data/backtest_nba_cache/`;
  every file there was compared against the manifest-verified decoded
  committed cache and is byte-identical, so the run consumed exactly the
  verified inputs. The committed harness file is byte-identical to
  `~/workspace/sportsedge-nba/scripts/validate_nba_game_markets.py` @
  `894950d6c`.
- Cache note: two pages (`scoreboard_20241128.json`,
  `scoreboard_20241218.json`) share one sha256 in the manifest because both
  are the same empty ESPN response (zero events). They contribute no games
  and no duplicates — the identical hash is explained, not an error.
- Universe as parsed by the harness: 310 completed games, 16 walk-forward
  splits (min_train=120, test_size=40, embargo 1 day) — matching the
  published design.

## Method (receipt conditions)

1. Cache verified against the manifest before use (above).
2. **Each game scored once, at its first test appearance**, using that
   split's train window (candidate = harness `price_fn` ratings replay on
   train only; naive = that split's train home-win rate — the same baseline
   the Oct 11 run used). The alternative receipt option (non-overlapping
   windows) was not needed.
3. **Per-game rows persisted**: `per_game_rows.csv` (this directory) — one
   row per distinct game with probabilities and per-game Brier/log loss
   for both models, the split/train size at first appearance, and the
   game's total appearance count.
4. Intervals: game-clustered bootstrap (each distinct game its own
   cluster, 20,000 paired resamples, seed 20261020).

Sanity check — before the fresh scoring, the original overlapping pipeline
was re-run unchanged and **reproduced the Oct 11 published aggregates
exactly**: candidate n=1306, Brier 0.2364, log loss 0.6652; naive n=1306,
Brier 0.2473, log loss 0.6877. The environment and inputs are the ones
that produced the published numbers.

## Results — fresh unique-game scoring

- Test appearances across the 16 splits: **653**; distinct games:
  **181**; duplicate appearances: **472 (72.3%)** — each distinct game
  appeared on average 3.6 times in the original scoring.

| model | distinct games | Brier | 95% cluster CI | log loss |
|---|---:|---:|---:|---:|
| candidate | 181 | **0.2383** | [0.2241, 0.2529] | 0.6691 |
| naive home-rate | 181 | **0.2477** | [0.2391, 0.2564] | 0.6885 |

- **Paired delta (candidate − naive): Brier −0.0094, 95% game-clustered
  CI [−0.0205, +0.0017]; log loss −0.0194, CI [−0.0425, +0.0039].**
- Home-win base rate on the 181 unique games: 0.547.

## What this says about the Oct 11 CONDITIONAL_PASS

- The **direction survives**: on unique games, scored once each, the
  candidate's point estimates still beat the naive home-rate baseline on
  both Brier (0.2383 vs 0.2477) and log loss (0.6691 vs 0.6885), by
  roughly the published margins.
- The **precision does not**: both paired intervals include zero. The
  published n=1306 counted each game ~3.6 times on average (653
  appearances of 181 distinct games, doubled to 1306 complementary
  records), so the original report's implied sample was overstated
  ~3.6×; at the true game-level n=181 the candidate-vs-naive gap is
  **not statistically distinguishable from zero**.
- The market-baseline leg remains MISSING (no market data exists in this
  cache), so nothing here can raise the verdict either.
- **Conclusion: the fresh run neither confirms the CONDITIONAL_PASS as
  stated nor reverses its direction. It replaces unverifiable with
  measured: candidate modestly ahead of naive on unique games, interval
  covering zero, market leg untested. CONDITIONAL_PASS remains
  unsupported as a precision claim.**

## Adapter notes (no silent changes)

The committed harness was not modified. The fresh run drives it through
its own functions (`fetch_games`, `build_fixtures`, `price_fn`,
`settle_fn`) from a separate driver script because (a) the harness's
`main()` would overwrite the branch validation report and only emits the
overlapping aggregates, and (b) first-appearance scoring and row
persistence are the receipt's conditions, which the original driver
never implemented. Driver: `~/workspace/tmp/nba-harness-fresh/fresh_run.py`;
machine-readable summary: `fresh_run_summary.json` (this directory).
