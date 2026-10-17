# Reproduction — batter props family (ruling 5, Oct 17 2026)

**Status:** reproduction record only. Not a certification and not an adoption. Family states and holds are unchanged.

## What was run
- The committed `scripts/eval_challenger_batter_props.py` (head `cd5b668c`) was run in `score` mode against evaluand worktree `2a713380c`. Prereg hash `58a7977c…1a65e3b` (the true hash, per the hash amendment) passed its own check.
- The committed parity and verification files were used as is. Parity needs live StatsAPI fetches, which this sandbox cannot make.
- Data: staging run **39032124764** (COMPLETE for 2024, 2025 and 2026; `ACQUIRED_POSTHOC_FROM_PUBLIC_STATSAPI`; never a pregame snapshot or a #2344 original). It supplied the 2026 hitting gameLogs (674), the players list, the monthly schedule and 2,429 boxscores.

## Deviations (none touch scoring)
1. **Schedule keys.** The evaluator's schedule cache keys use `&hydrate=linescore`; the staged schedule does not. The staged March–September 2026 payloads were filed under the evaluator's keys. The evaluator reads only gamePk, gameType, officialDate, gameDate and team names, which are all present.
2. **Acquisition record fields.** The acquisition record's `players_2026`, `gamelog_urls` and `schedule_urls` fields hold provenance text, not the original counts.
3. **Phase 2 B1/B2 line quote.** The Phase 2 script `backtest_program_20261014/scripts/eval_batter_props.py`, which the evaluator only quotes lines from into the report, is not in any branch. The quote list is left empty. It was not fabricated.

## Result: exact reproduction
- **Fixtures:** 38,511, identical to the original. Exclusions are identical: POOL_GAMES_LT_10 5,184, NOT_A_STARTER 5,919, POOL_PA_LT_20 10.
- **All 13 verdicts are identical:**
  - ADOPT-CANDIDATE for HITS, TOTAL_BASES, RUNS, H+R+RBI, SINGLES, WALKS, HOME_RUNS, EXTRA_BASE_HITS, STRIKEOUTS and RUNS+RBIS.
  - KEEP FROZEN for RBIS, DOUBLES and TRIPLES.
- **Every number in `stats`:** max absolute difference **2.2e-16** (floating-point summation order). No non-numeric field differs.
- **The one bookkeeping difference:** game 823490 (BAL@NYY, Cancelled) has no boxscore in the staged data, because the job fetches boxscores only for played games. So it shows as BOXSCORE_UNAVAILABLE instead of "starter count 0". It contributes no fixtures in either run.

## With the pitcher record
Together with `REPRODUCTION_PITCHER_UNDERCARD_20261017.md`, all MLB families in #2368 are now independently reproduced. The CFB QB family is still not reproduced.
