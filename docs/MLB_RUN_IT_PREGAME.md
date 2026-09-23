# MLB RUN IT automatic pregame stack

`sportsedge.mlb_run_it_pregame` is the public-source pregame acquisition bundle for a single `game_pk`.

It does **not** use The Odds API or any paid commercial key. DraftKings quotes are not scraped or acquired by this module. They may be supplied natively/manually and never enter Model_P or governed evidence merely because they were supplied to the bundle.

## Implemented on this branch

1. probable starters from the MLB live feed
2. confirmed batting-order IDs from the MLB live-feed boxscore
3. home-plate umpire assignment and governed tendency context
4. roster / IL / transaction context plus lineup-change scratch evidence
5. prior-day Statcast rolling windows + optional Baseball Savant Game Preview provenance
6. park / venue binding from public StatsAPI venue metadata
7. weather from the National Weather Service point -> hourly forecast flow, with static roof type preserved and retractable-roof state left UNKNOWN unless a future authoritative source proves it
8. native/manual DraftKings HYBRID quote intake using the canonical `INTAKE_STAMPED` timestamp policy

Every public context lane emitted by this bundle carries `model_p_eligible=false`. Native/manual DraftKings quote rows also carry `model_p_eligible=false` and `evidence_eligible=false`.

`unimplemented_lanes` is empty for the acquisition contract in v2. This does **not** mean every lane is predictive or validated; it means the promised acquisition/context surfaces are present.

## Park / venue

`sportsedge.mlb_park_venue_source` binds `gameData.venue.id` to the public StatsAPI venue endpoint using `hydrate=location,fieldInfo,timezone`.

The lane retains venue ID/name, location, coordinates, timezone, roof type, turf type, capacity, and available field dimensions. Missing venue IDs or failed venue fetches fail closed and are reported explicitly.

## Weather / roof

`sportsedge.mlb_weather_roof_source` uses venue latitude/longitude with the public NWS `/points/{lat},{lon}` discovery endpoint, then follows `forecastHourly`. The forecast period nearest scheduled first pitch is retained.

The weather lane records temperature, wind speed/direction, precipitation probability, and short forecast when available. If NWS does not cover the coordinates or the request fails, status is `UNAVAILABLE`; the bundle does not invent weather.

`roof_type` is static venue metadata. `roof_state` remains `UNKNOWN` because a retractable roof being present does not prove whether it will be open or closed for that game.

## DraftKings HYBRID intake

`sportsedge.mlb_dk_hybrid_source` accepts only caller-supplied DraftKings rows. It does not scrape DraftKings and does not call an odds aggregator.

It reuses SportsEdge's canonical HYBRID quote timestamp policy:

- supplied timezone-aware `retrieved_at` -> `timestamp_source=PROVIDED`
- missing/blank `retrieved_at` -> stamp the bundle intake time and label `timestamp_source=INTAKE_STAMPED`
- invalid or naive supplied timestamps fail closed

`INTAKE_STAMPED` means only "SportsEdge received this line at this time." It does **not** mean the sportsbook price was first observed then, and it is not valid CLV/replay/Truth Gate/OFFICIAL evidence.

The CLI accepts a JSON list (or `{ "quotes": [...] }`) with `--dk-quotes`:

```bash
python scripts/run_it_mlb_pregame.py 776123 \
  --dk-quotes artifacts/manual/dk_quotes.json \
  --out artifacts/mlb/pregame/776123.json
```

## Umpires

Assignment is resolved in this order:

1. live-feed boxscore officials
2. StatsAPI `schedule?hydrate=officials` for the official date

The `jobs/umpires/games/{id}` history route is not used. Prior home-plate assignments are recovered from the public schedule officials board and their public boxscores.

K/BB/run game totals are Empirical-Bayes shrunk toward the frozen prior in `config/mlb_umpire_prior_v1.json`. The v1 baseline uses 2025 MLB per-team-game league averages of 4.45 runs, 8.36 strikeouts, and 3.16 walks, doubled to game totals (8.90, 16.72, 6.32). `prior_equivalent_games=8` is a governance hyperparameter, not an empirical sample-size claim. Samples under `min_home_plate_games=8` contribute an exact zero delta. Any prior change requires a new versioned config.

## Scratches

Transaction descriptions containing an explicit scratch remain preserved as `explicit_scratches`, but that is not treated as a complete late-scratch detector.

The source can also compare a previously captured posted batting order (`baseline_lineup_ids`) with the current posted batting order. A player removed from a posted lineup is emitted as `POSTED_LINEUP_REMOVAL` evidence.

If no prior posted lineup exists, the result is `scratch_detection_status=NOT_EVALUABLE`; it is **not** represented as a clean zero-scratch result. If a baseline and current lineup are both available and no removal/explicit scratch is found, the result is `EVALUATED_NO_EVIDENCE`.

## Statcast

`mlb_statcast_preview_source` binds the existing prior-day Statcast window onto probable pitchers and batting-order/player IDs. Probable pitchers are read from `gameData.probablePitchers` even when the boxscore has not posted yet.

Baseball Savant Game Preview HTML capture is optional and **off by default** so deterministic CI does not make that network request. Passing `--statcast-html` enables it explicitly.

## Deterministic tests

The pregame source tests use injected fixtures/openers and do not require live network access. They cover:

- probable pitchers before a boxscore exists
- Statcast HTML skipped by default
- scratch state not evaluable without a lineup baseline
- posted-lineup removal evidence
- live-boxscore umpire assignment
- schedule-hydrate umpire fallback
- exact zero umpire delta below eight HP games
- EB shrinkage at the eight-game floor
- venue/coordinate/roof parsing
- nearest-hour NWS forecast selection
- fail-closed weather when coordinates are unavailable
- DraftKings-only quote enforcement
- `PROVIDED` versus `INTAKE_STAMPED` quote timestamps
- the unified bundle with all acquisition lanes present and outside Model_P

## CLI

```bash
python scripts/run_it_mlb_pregame.py 776123 --out artifacts/mlb/pregame/776123.json
```

Use `--statcast-html` only when an HTML capture is intentionally wanted. Use `--dk-quotes` only for caller-supplied native/manual DraftKings rows.
