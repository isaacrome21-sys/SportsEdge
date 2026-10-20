# Oct 11 NBA harness — outcome cache, script, and design docs

Committed by Rocky (Muse lane), Oct 19, 2026, so the fresh NBA harness
run required on issue #2410 can be executed and audited from either
chair. Source of every file: the `feat/nba-20261011` checkout at
894950d6c in Rocky's workspace, where the cache lived untracked
(gitignored) and was never part of any merged commit.

## Contents

- `cache/` — the 43 ESPN scoreboard responses the Oct 11 harness read
  (`scoreboard_YYYYMMDD.json`, 4.5 MB total), each stored gzip-compressed
  and base64-encoded as `<name>.json.gz.b64` because the records push
  path is text-only. Decode: `base64 -d <name>.json.gz.b64 | gunzip`.
- `MANIFEST.sha256` — sha256 of each DECOMPRESSED cache file. All 43
  files were round-trip verified against this manifest before commit.
- `harness/validate_nba_game_markets.py` — the harness driver as it ran.
- `docs/` — the feasibility design and the validation report as published.

## What this cache is — and is not

These files are OUTCOMES ONLY (final scores). The Oct 11 run's per-game
predictions were held in memory and never persisted anywhere, so the
published CONDITIONAL_PASS (candidate Brier 0.2364 vs naive 0.2473 over
1,306 complementary home/away records = 653 test appearances drawn
from 310 distinct games through 16 overlapping walk-forward splits)
**cannot be re-scored from this or any other record**. It remains
unsupported and unverifiable, as #2410 states.

A fresh run from this cache is a NEW evaluation, not a re-score. Per
the #2410 close-out, it must: (1) verify the cache against
MANIFEST.sha256 before use; (2) use non-overlapping test windows, or
score each game once at its first test appearance; (3) persist per-game
rows this time, and report distinct games, duplicate appearances, and
Brier scores with a game-clustered interval. The baseline in the Oct 11
design was a naive home-win rate — there is no market leg in this data.
