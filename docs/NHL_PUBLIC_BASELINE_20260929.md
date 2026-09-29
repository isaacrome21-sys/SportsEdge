# NHL public-boxscore baseline — 2026-09-29

Status: **development baseline only**. This document creates no Model_P, Truth Gate, OFFICIAL, staking, promotion, or historical betting-evidence authority.

## Why this slice exists

SportsEdge already has a coherent NHL shared-goal simulator, period/player derivative engines, market pricing, PIT feature contracts, role/event binding, and a richer xG-oriented rate model. The missing practical gap is a reproducible fitted artifact fed by public historical hockey data rather than hand-entered rates.

The official NHL Gamecenter boxscore exposes completed-game goals, shots on goal, power-play conversion, linescore periods and player/goalie boxscore rows. This slice turns that public result stream into a separate non-xG baseline so ordinary goals/shots statistics are never mislabeled as expected goals.

## Public references reviewed

The implementation is original SportsEdge code. Public repositories were used as endpoint/schema documentation and design references only.

- `pseudo-r/Public-NHL-API` (MIT), `docs/web-api/games.md`: documents `GET /v1/score/{date}` and `GET /v1/gamecenter/{game-id}/boxscore`, including the current Gamecenter response families.
- `Zmalski/NHL-API-Reference` (MIT), `README.md`: independent reference for `api-web.nhle.com` schedule, score, roster, player and Gamecenter endpoints.
- Public NHL application type definitions were reviewed only to cross-check current boxscore field names such as `startTimeUTC`, `awayTeam`, `homeTeam`, `boxscore.linescore.byPeriod` and `boxscore.playerByGameStats`. No external source code is copied into SportsEdge.

The richer xG path remains separate. Public xG repositories were reviewed for general feature families (location/distance, angle, shot type, strength state, rebound/rush and shooter/goalie context), but no GPL/unclear-license implementation or fitted coefficient is copied.

## Receipt contract

`sportsedge/sports/nhl/official_boxscore_source.py`:

- accepts only final/off official Gamecenter boxscores;
- binds the exact official source URI and SHA-256 of raw response bytes;
- records the real retrieval timestamp;
- separates regulation goals (periods 1–3) from final goals after OT/SO;
- parses team SOG, PP conversion and goalie rows when available;
- fails closed on malformed identity, incomplete regulation linescore, invalid counts, bad source URI or bad hash;
- round-trips normalized receipts deterministically.

A historical game fetched today is known to SportsEdge **today**. Its row can be used for model development and future predictions, but the repository does not pretend it was captured before an old historical target game. This is intentionally different from forward evidence.

## Baseline feature model

`sportsedge/sports/nhl/public_baseline.py` constructs each game row before adding that game's result to team history. The frozen v1 feature vector is:

1. offense regulation goals per game;
2. opponent regulation goals allowed per game;
3. SOG share using offense SOG-for and opponent SOG-against history;
4. power-play percentage minus opponent penalty-kill percentage;
5. offense regulation shooting percentage;
6. opponent regulation save percentage inferred from regulation GA/SOG-against history;
7. days-since-last-game differential;
8. home-ice indicator.

The fit is a standardized ridge regression on `log(regulation_goals + 0.5)`. The artifact stores frozen feature names, means/scales, coefficients, ridge value, training-row count, deterministic training SHA-256 and training time range. It feeds the existing shared `NHLGameState` simulator but is deliberately named `public_baseline` rather than pretending boxscore statistics are xG.

The chronology rule is tested: changing a target game's result cannot change that game's pregame feature vector, and a game starting after the target puck drop cannot change the target matchup features.

## Collection and fitting

The two CLI tools are intentionally separate:

```bash
python scripts/collect_nhl_official_boxscores.py \
  --start-date 2023-10-01 --end-date 2026-09-28 \
  --output data/nhl/development/official_boxscores.jsonl

python scripts/fit_nhl_public_baseline.py \
  --input data/nhl/development/official_boxscores.jsonl \
  --output data/nhl/development/public_baseline_v1.json \
  --version nhl-public-boxscore-baseline-v1
```

The collector traverses the official score feed, de-duplicates completed regular-season/playoff game IDs, fetches each official boxscore, records raw SHA-256 + retrieval time, supports resume, and exits nonzero on partial failure unless explicitly told otherwise.

The fitter emits a deterministic development artifact plus the normalized source-dataset hash. It does not create historical wager evidence or automatically promote the baseline.

## What still blocks production/model promotion

This baseline can produce genuine SportsEdge-generated goal rates and shared simulation probabilities once an artifact is fitted, but it is not yet a promoted Model_P. Remaining work includes:

- run the public-data collection and fit on a frozen dataset;
- temporal holdout diagnostics and calibration on model-development history;
- forward pregame feature snapshots and paired market quotes from the date of capture onward;
- explicit goalie starter confirmation/invalidation rather than roster membership alone;
- xG artifact fitting from the staged official PBP path or another licensed/provenance-safe shot-history source;
- market-level settlement/CLV/forward validation before any Truth Gate/OFFICIAL authority.

No historical prices are backfilled by this slice.
