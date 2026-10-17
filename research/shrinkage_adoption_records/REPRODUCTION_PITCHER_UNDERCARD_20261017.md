# Reproduction — pitcher undercard family (ruling 5, Oct 17 2026)

**Status:** reproduction record only. Not a certification and not an adoption. Family states and holds are unchanged.

## What was run
- The committed evaluator `scripts/eval_challenger_pitcher_undercard.py` (head `cd5b668c`) was run unmodified in `score` mode.
- Evaluand worktree: `2a713380c`. Prereg hash `9628b962…a85ca25` passed its own check.
- The committed parity file was used as is. The parity phase needs a live StatsAPI fetch, which this sandbox cannot make, so it was not re-run.
- Data: staging run **39027576218** (COMPLETE, `ACQUIRED_POSTHOC_FROM_PUBLIC_STATSAPI`; never a pregame snapshot or a #2344 original).
  - The run's 2026 pitching gameLog, schedule and players payloads were laid out under the evaluator's own cache-URL scheme.
  - The staged gameLog URLs carry `&gameType=R`. They were re-keyed to the evaluator's URL form. Payload bytes are unchanged.

## Result
- **All four verdicts and every gate flag reproduce:** OUTS, HITS_ALLOWED and BB are ADOPT-CANDIDATE; ER is KEEP FROZEN. Every `entirely_below_zero` flag is identical.
- **The population differs slightly:**
  - 4,858 regular-season starts against the original 4,844. The original cache lacked 14 starts.
  - So 3,391 fixtures are scored against the original 3,382.
  - Numbers shift in the 3rd–4th decimal. Example, OUTS CRPS: challenger 2.0489 vs 2.0512; B2 2.1685 vs 2.1705.
- **This lane's B2 construction is confirmed.** B2 OUTS 2.1685 reproduces the lane's 2.1705, not the parallel run's 2.0267 (REPORT flag 2).

## Hashes
- Four prereg tokens in `specs/SPEC_HASHES.txt` match the files on disk.
- The batter-props token is 55 characters long, a 9-character transcription drop. The file's true SHA-256 is `58a7977c…1a65e3b`, already recorded before scoring in `AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md`. That file's own hash `a1cd3f72…902e` was recomputed here.

## Not reproduced here
- **The 10 batter families:** they need batter gameLogs and boxscores, which the staging job does not acquire.
- **The CFB QB family:** it needs its own sources.

Both stay unreproduced until data is acquired under ruling 9, staging only.
