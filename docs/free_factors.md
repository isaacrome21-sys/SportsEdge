# SportsEdge Free Factors (Phase 2)

Every factor: **free verified sources only, zero API keys, zero paid services,
zero infrastructure for Isaac to run.** Each factor is gated on the backtest
harness (`sportsedge/backtest`): it must improve chronological out-of-sample
Brier **and** log-loss vs the existing model before entering production
pricing. No market baseline exists (no Odds API by Isaac's choice), so the
best achievable verdict is **CONDITIONAL_PASS** — labeled as such, never
presented as a validated edge. Market prices are never model features
(market-blind discipline); archived odds may serve only as the harness
evaluation baseline via Actions-side archival.

## Factor library (`sportsedge/free_factors.py`)

| # | Factor | Source (free, verified) | Pricing use |
|---|--------|------------------------|-------------|
| 1 | MLB park factors | MLB StatsAPI schedule 2022–2024, derived by `scripts/derive_mlb_park_factors.py` | scales both teams' run means (half-strength, bounded ±8%) |
| 2 | Rest / travel | ESPN team schedules + Open-Meteo geocoding (static geography) | declared rest differential / travel burden adjust NFL/CFB means |
| 3 | Weather thresholds | Open-Meteo API + MLB StatsAPI venue azimuth/coords | declared wind/precip buckets adjust totals |
| 4 | NFL/CFB key numbers | ESPN scoreboards 2020–2023 (NFL) / 2021–2023 (CFB), `scripts/derive_key_number_table.py` | empirical push blend for SPREAD/TOTAL integer lines |
| 5 | MLB umpire | — | **NOT_WIRED**: no stable free pregame source (historical only in boxscores) |
| 6 | Injury / participation | ESPN injuries API (team-identity-verified) | declared QB-out adjustment; **NOT_VALIDATABLE** (no archived injury feed) → stays HEURISTIC_NOT_VALIDATED, fail-closed |
| 7 | MLB starting pitcher | MLB StatsAPI probablePitcher + game logs | declared ERA-based adjustment to opponent's mean |
| 8 | MLB bullpen workload | MLB StatsAPI boxscores | declared trailing-3d pitches fatigue adjustment |
| 9 | Backups / depth | — | **NOT_INVENTED**: who's out is verified; backup quality has no free measure |
| 10 | MLB rotation (days rest) | MLB StatsAPI game logs | declared short-rest penalty |
| 11 | Team strength (SRS) | ESPN/StatsAPI scores | opponent-adjusted predicted margin |
| 12 | Venue-specific HFA | ESPN/StatsAPI scores | shrunk team home-edge delta |
| 13 | Pace (NFL) | ESPN summaries `totalOffensivePlays` | declared plays/game total adjustment |
| 14 | Turnovers regressed (NFL) | ESPN summaries `turnovers` | removes 70%-regressed turnover luck from means |
| 15 | MLB starter FIP | MLB StatsAPI game logs | declared FIP-based adjustment to opponent's mean |
| 16 | NFL EPA/play | nflverse play_by_play CSVs (GitHub releases) | trailing-8-week EPA strength → margin |

**Fail-closed everywhere:** any unverifiable input → `(0.0 / 1.0, <REASON>, ...)`
and the ingestion stage must not apply a pricing effect. Reason codes are
explicit (`PARK_FACTOR_STALE`, `REST_UNVERIFIED`, `PITCHER_HISTORY_INSUFFICIENT`, …).

## Ingestion entry points (for the Phase 8 pre-pricing stage)

Every entry point returns:
```python
{"factor": str, "kind": "add"|"scale"|"push"|"margin"|"none",
 "target": "TOTAL"|"HOME_MARGIN"|"HOME_MEAN"|"AWAY_MEAN"|"OPPONENT_MEAN"|None,
 "value": float | tuple | None, "status": str, "detail": str,
 "source": str, "verified": bool, "applied_statuses": [...]}
```
Application rules:
- `add`/`TOTAL` → `home_mean += v/2; away_mean += v/2`
- `add`/`HOME_MARGIN` → `home_mean += v/2; away_mean -= v/2`
- `add`/`HOME_MEAN`|`AWAY_MEAN` → direct
- `add`/`OPPONENT_MEAN` (entry has `side`) → the other team's mean `+= v`
- `scale`/`BOTH_MEANS` → both means `*= v`
- `push` → `value` is `(win, push, loss)` replacing the base triple
- `margin` → `value` is the predicted home margin (replaces rating margin)
- `none` → audit-only; `verified=False` → **must not** price

Signatures:
```
ingest_mlb_park(home_team_name: str, season: int)
ingest_rest(sport: str, home_rest_days, away_rest_days)
ingest_travel(sport: str, traveler_side: str, miles, tz_jumps)
ingest_weather(sport: str, wind_speed_mph, wind_from_degrees=None,
               field_azimuth_degrees=None, precip_probability_pct=None, indoor=None)
ingest_key_numbers(sport: str, market: str, line, win: float, push: float, loss: float)
ingest_mlb_pitcher(side: str, probable_pitcher_name, era_prior, n_starts: int)
ingest_mlb_pitcher_fip(side: str, probable_pitcher_name, fip_prior, n_starts: int)
ingest_mlb_bullpen(side: str, trailing_3d_pitches, n_games: int)
ingest_mlb_rotation(side: str, days_rest)
ingest_participation(sport: str, team_side: str, qb_out_verified: bool, qb_name=None)
ingest_srs_margin(srs_table: dict, home_team: str, away_team: str, league_hfa: float)
ingest_venue_hfa(home_movs: list[float], road_movs: list[float], league_home_edge: float)
ingest_pace(home_plays_pg, away_plays_pg, league_avg_plays_pg)
ingest_turnovers(to_diff_per_game, team_side: str)
ingest_epa_margin(home_strength, away_strength, league_hfa=1.5)
ingest_time_decay(values_with_age: list[tuple[float, float]], sport: str)
ingest_weather_interaction(sport: str, temp_f=None, humidity_pct=None,
    park_factor=None, pass_rate=None, base_wind_adj=0.0, indoor=None)
umpire_entry()  # NOT_WIRED
```

### Layer interfaces for the Elo-foundation agent

The Elo agent owns team-strength ratings. Our layers plug in via the entry
points above: each `ingest_*` takes the Elo agent's means (or margins) plus
verified factor evidence and returns an adjustment entry. The contract:
- Elo agent produces base `home_mean`, `away_mean` (or a margin).
- Each factor layer calls its `ingest_*` with those means + evidence.
- Adjustments compose by the application rules above (additive on means).
- Every layer emits a coverage entry (`verified` bool + status code) for
  the per-selection factor-coverage audit.
- Time-decay (`ingest_time_decay`) is a rating-construction input: the Elo
  agent should weight game margins by `time_decay_weight(days_ago,
  half_life)` with the declared per-sport half-lives in
  `TIME_DECAY_HALF_LIFE_DAYS` (MLB 30d, NFL 45d, CFB 30d, NBA 30d).

### Park factor derivation note (bug fix 2026-10-11)

The first park table was wrong: the MLB StatsAPI schedule endpoint
**ignores the `team=` query parameter** (verified by direct test — filtered
vs unfiltered queries return identical game counts). The derivation counted
every non-home game as a "road" game, polluting the road sample. Fixed in
`scripts/derive_mlb_park_factors.py`: fetch full-season schedules, group by
team locally. Table re-derived from 2022-2024 (30 teams, ≥200 home games
each). Rockies 1.161, Mariners 0.917, Red Sox 1.069, Marlins 1.076.

### Exponential decay spec (architecture critique adoption)

Fixed-window blending (last-5 equal-weighted) is replaced by declared
per-sport exponential decay: `weight = 0.5^(days_ago / half_life)` with
half-lives in `TIME_DECAY_HALF_LIFE_DAYS`. Validated: decay-weighted NFL
ratings beat equal-weighted windows OOS (CONDITIONAL_PASS, Brier
0.2467→0.2438). The SRS already used decay (45d); the 5-game rating windows
now use it too.

### Weather interactions (architecture critique adoption)

Beyond base thresholds: `weather_interaction_adjustment` implements
- **NFL wind × passing**: base wind suppression scaled by `(0.5 +
  combined_pass_rate)`; pass rate from nflverse, unverified → fail closed.
- **MLB temp/humidity × park**: +0.025 runs/°F from 70°F (capped ±0.75);
  humidity ≥70% in heat ≥75°F amplifies ×1.25; multiplied by the runs park
  factor when verified. Capped ±1.0 runs.
All coefficients are declared priors, harness-gated.

### Scope split: Statcast (2026-10-11)

Baseball Savant Statcast features (exit velocity, xwOBA, pitch-level
quality) are owned by a **dedicated Savant agent** — do not duplicate.
This phase keeps **box-score-derived pitching metrics only**: FIP/SIERA,
ERA/WHIP, K/BB rates (from MLB StatsAPI box scores/game logs, free).
The Savant agent exposes its own entry point for the factor pipeline;
coordinate via the `ingest_*` interface contract, not by reimplementing.

### Derek Carty / THE BAT adoptions (2026-10-11)

Methodological pattern: **component-level decomposition, regress-by-noisiness**.

1. **Component park factors** (`ingest_component_park`): from Retrosheet
   play-by-play (free event files), computed SEPARATELY for 1B/2B/3B/HR/BB/K
   via road-weight (team home rate vs road rate) + declared per-component
   regression. **Replaces** the aggregate-runs park factor.
   Derivation: `scripts/derive_component_park_factors.py`.

2. **Regressed platoon splits** (`ingest_platoon`): heavily regressed —
   RHB to ~2,200 PA / LHB to ~1,000 PA of league average. Power splits >>
   contact splits. Raw splits are noise that manufactures fake edges —
   never use unregressed splits.

3. **Stabilization points** (`STABILIZATION_PA`): declared per-stat
   thresholds (e.g., K% 60 PA, BB% 120 PA, BABIP 650 PA). This IS the
   declared recency-weighting spec — regression-by-noisiness per component,
   not one blanket decay. `regress_stat()` implements it.

4. **Umpire zone effects** (K/BB): MISSING until proven stable OOS.
   Validation path: derive umpire deltas from Retrosheet info records,
   test cross-season stability in walk-forward.

5. **Catcher framing**: MISSING until proven stable OOS. Same validation path.

All harness-gated per the standing bar.

### X-sweep sourced additions (2026-10-11)

**UmpScorecards.com** (umpscorecards.com): daily + historical (2015–) MLB
umpire ball/strike accuracy with "accuracy above expected" and published
explainers. **API assessment**: the site is a SvelteKit JavaScript app; no
keyless JSON API endpoint was found via inspection (data loads client-side).
Scraping the rendered pages would be fragile and against the "stable free
source" requirement. **CRITICAL CAVEAT**: MLB's ABS challenge system (2026)
structurally shrinks the umpire effect — the factor stays MISSING until the
harness proves a residual post-ABS. Do NOT over-invest here. If a stable
data path emerges, the validation path is: umpire K/BB deltas → test
cross-season stability in walk-forward → wire only if stable.

**MySportsWeather.com** (mysportsweather.com): free venue-level forecasts
(NFL/CFB pages with hourly wind/temp/precip). Their published reads for
calibrating our declared thresholds:
- **Wind is the #1 football factor** — aligns with our football wind
  thresholds (15 mph moderate / 20 mph strong). No change to constants
  without harness validation.
- **Cold is overrated by the public** — we have no cold threshold (correct;
  do not add one on narrative).
- **Temp/air-density effects are large and park-specific (MLB)** — aligns
  with our `weather_interaction_adjustment` temp×park term. The interaction
  is the right structure; coefficients stay declared until harness-validated.
- Do NOT rely on their OVERcast app (assume paid). Use only the free
  forecast pages for threshold calibration context, never as a pricing input.
- **Rule**: any quantified claim (e.g., "x mph wind = y points") needs
  harness validation before becoming a constant. The current thresholds
  are declared priors, not calibrated values.

## Weather evidence sourcing (keyed API pattern)

A weather API key exists **only as a GitHub Actions secret**. Rules:
1. The key is referenced **only** as `${{ secrets.* }}` in workflow YAML,
   usable **only** from GitHub Actions server-side.
2. Follow the established pattern of `.github/workflows/cfb-forward-weather-evidence.yml`:
   Actions pull weather → archive evidence **append-only** to the `data`
   branch (`history/<sport>/weather/`) → the runner reads the **archived**
   data.
3. **NEVER** call the keyed API from the phone runner, local code, or this
   validation tooling; **never** print/log the key value; respect whatever
   budget the workflow defines.
4. The weather factor keeps its declared-threshold design
   (`weather_total_adjustment`): the evidence archive is only the sourcing
   path for pregame production. Harness validation uses the free no-key
   ERA5 archive (`archive-api.open-meteo.com`), which is the validation
   sourcing path and stays key-free.

The same Actions-side pattern applies to the Odds API keys
(`SPORTSEDGE_ODDS_API_KEY[_2/_3/_4]`): archive workflows write closing-line
evidence to the data branch; keys stay on the **evaluation/archival** side
only. Market prices are **never** pricing features.

## Guardrails (non-negotiable)

1. **Market-blind:** market odds are never model features. Archived prices
   may serve only as the harness evaluation baseline.
2. **Scope:** our sports are NFL/CFB/MLB/NBA/CBB. NHL/Soccer are out of scope.
3. **NOT_WIRED:** motivation spots, coaching tendencies, news speed —
   no verifiable free source; never attempted. Umpire/referee effects only
   with a stable free pregame source (none exists → NOT_WIRED).
4. **Backups:** who's out is verifiable; backup quality is never invented.
5. **Research-only:** no betting authority, no staking, no official picks.

## Validation

Run with `cwd=~/workspace/sportsedge-backtest` (do not copy the harness):
```
python3 ~/workspace/sportsedge-freefactors/scripts/validate_free_factors.py <factor|all>
```
Per-factor JSON reports land in `docs/validation_reports/`. Verdicts are
summarized in `docs/free_factors_validation.md`.

Derivation scripts (re-verifiable provenance):
- `scripts/derive_mlb_park_factors.py` → `data/park_factors_2022_2024.json`
- `scripts/derive_key_number_table.py` → `data/key_number_margins.json`

## Adversarial testing (standing practice)

Isaac's directive: "try to break it, fix it, improve, refine." Every factor
is red-teamed before shipping (`tests/test_adversarial_factors.py`):

**Factor-level attacks** — stale inputs (park table past `PARK_FACTOR_MAX_SEASON`,
moved teams), missing inputs (null/None everywhere), contradictory inputs
(negative rest days, negative miles, precip > 100%, NaN lines, NaN wind).
Every attack must produce an explicit fail-closed reason code, never a
silent default or a crash.

**Bugs the red team has caught and fixed:**
1. `rest_margin_adjustment(-3, 6)` silently clamped a contradictory negative
   rest to −0.9 pts → now `REST_UNVERIFIED` ("negative rest days").
2. `key_number_push_probability("NFL", NaN, …)` raised `ValueError` at
   `int(round(abs(NaN)))` → now fail-closed to the normal push.
3. `weather_total_adjustment` accepted `precip_probability_pct=150` →
   now `WEATHER_UNVERIFIED` (probability must be in [0,100]).
4. `ingest_key_numbers` returned `kind="push"` with the unchanged triple on
   factor failure → now `kind="none"` (audit-only) when not verified.

**Gate-level attack** — a spurious correlation is planted in the early
synthetic data so a noise factor looks predictive **in-sample** (researcher
thinks they found an edge); the walk-forward harness gate must still reject
it out-of-sample. Verified: the gate returns **FAIL** for the spurious
factor and for fixed noise, while a genuinely predictive factor earns
**CONDITIONAL_PASS** (baseline missing). The gate's defense is the strict
improvement requirement on both Brier and log-loss plus chronological
splitting — in-sample fitting cannot leak across the split boundary.

**Test-design fix (2026-10-11):** the spurious-correlation test initially
planted the fake signal in the first 60% of fixtures, but walk-forward test
sets starting at i=80 overlapped the planted region (i<144), so the
spurious factor legitimately helped in early test splits and the gate
correctly returned CONDITIONAL_PASS — the test was wrong, not the gate.
Fixed: plant only in i<80 (the initial training window, never in any test
set). The gate now correctly FAILs the spurious factor.

**New factor attacks (2026-10-11):**
5. Time-decay: year-old games get near-zero weight (not equal weight);
   negative age (future game) raises `TIME_DECAY_NEGATIVE_AGE`.
6. Weather interactions: missing temp/pass rate → `WEATHER_INTERACTION_UNVERIFIED`
   (fail closed, not silent zero); implausible temp (200°F) or pass rate >1
   → fail closed.
