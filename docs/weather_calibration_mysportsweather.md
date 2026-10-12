# Weather Threshold Calibration — MySportsWeather Reads (2026-10-11)

X-account review item 2 (Bucket A). MySportsWeather.com (@KevinRothWx) is a
free venue-level forecast source. Their OVERcast app is assumed paid — never
relied on; our weather evidence stays on the keyless Open-Meteo path
(`WEATHER_SOURCE` in `sportsedge/free_factors.py`), ERA5 archive for harness
validation, Actions-side keyed API only for pregame archival per the
established pattern.

## Their published reads (paraphrased, with mapping to our declared constants)

1. **Wind is the #1 weather factor in football; cold is overrated by the
   public.** Independent analyses agree on the mechanism: wind disrupts ball
   flight, and passing accuracy declines once winds pass ~15 mph in open
   stadiums. → Our football constants are **wind-only**: `FOOTBALL_WIND_MODERATE
   = 15`, `FOOTBALL_WIND_STRONG = 20` (mph), adjustments −0.75/−1.50 pts.
   **Calibration decision: no temperature/cold coefficient is added for
   football** — consistent with "cold overrated". Any cold effect stays at
   zero until the harness proves otherwise (nothing ships on vibes).
2. **Temperature/air-density effects are large** (hot air is thinner → ball
   carries; cold air is denser → lower scoring; humid air is counterintuitively
   *less* dense → ball carries farther). → Our MLB interaction:
   `weather_interaction_adjustment` (MLB branch): +0.025 runs/°F above 70°F
   (capped ±0.75), humidity ≥70% in heat ≥75°F amplifies ×1.25. Direction is
   aligned with their reads; **the coefficient value is a declared prior and
   becomes a constant only if the harness validates it** (`weather_interaction`
   runner: declared-thresholds vs thresholds+interaction).
3. **Effects are park-specific** (ballpark microclimates; Wrigley's wind is
   famously amplified — published reads put 10 mph at Wrigley on par with far
   stronger winds elsewhere). → We do **not** invent a Wrigley-specific wind
   multiplier. The interaction term multiplies by the verified runs park
   factor (hitter parks amplify carry, pitcher parks mute it) — a declared
   approximation. A dedicated park×wind coefficient needs its own harness
   validation; it is **not** wired here.

## What is harness-gated here

- `weather` (declared wind/precip thresholds vs legacy heuristic): **FAIL**
  (Brier 0.2320→0.2321) — `docs/validation_reports/weather.json`.
  `ingest_weather` is audit-only until a future validation passes.
- `weather_interaction` (declared temp/humidity × park on top of the
  thresholds): CONDITIONAL_PASS vs thresholds — `docs/validation_reports/
  weather_interaction.json`. Informational only: it stacks on a failed base.
- `weather_interaction_legacy` (temp/humidity × park stacked on the legacy
  heuristic): **CONDITIONAL_PASS** (Brier 0.2320→0.2312, LL 0.7120→0.6985,
  n=11575) — `docs/validation_reports/weather_interaction_legacy.json`.
  **The +0.025 runs/°F temp coefficient is now a validated constant** (labeled,
  research-only, CONDITIONAL on the missing market baseline per the standing
  bar). Wired via `ingest_weather_interaction("MLB", ...)` → kind `add`,
  target `TOTAL`. The ×park multiplier leg was fail-closed off in the run
  (2025 → PARK_FACTOR_STALE) and stays forced off; the NFL wind × pass-rate
  leg and the declared precip thresholds are NOT validated and stay
  audit-only.
- New runners added to `scripts/validate_free_factors.py`
  (`_run_weather(..., apply_interaction, base)`); ERA5 `temperature_2m` /
  `relative_humidity_2m` fetched under a separate cache key (`era5t_*`) so
  the existing wind/precip cache is untouched. Two pre-existing script bugs
  fixed: ERA5 naive-vs-aware datetime crash, and ERA5 archive serving
  all-null `precipitation_probability`.

## Honest limitations

- ERA5 archive has no `precipitation_probability` (verified all-nulls
  2026-10-11) — the harness validates the **wind leg only**; the declared
  precip thresholds (MLB −0.30 / football −0.75 at ≥70%) are not exercised
  OOS. Production pregame (Open-Meteo forecast API) does provide
  precipitation_probability, so the thresholds stand as declared priors,
  unvalidated.
- The harness fixture window is MLB Jun–Aug 2025: almost no sub-70°F games, so
  the cold-side leg of the temp coefficient is barely exercised. Any verdict
  rests on the 70–100°F range; extending to April/October fixtures is a
  follow-up if the summer leg passes.
- ERA5 reanalysis (not forecast) is the validation weather source — correct
  for backtesting (what actually happened), but production pregame uses
  forecasts; the forecast-vs-actual gap is a separate, unmodeled error term.
- `park_factor_for` for 2025 returns `PARK_FACTOR_STALE` (table is 2022–2024),
  so the interaction run exercises the temp/humidity leg with the park
  multiplier fail-closed off — the ×park leg is NOT what gets validated here.
- Football wind thresholds are validated nowhere in this pass (the harness
  `weather` run is MLB-only); the NFL wind × pass-rate interaction needs the
  NFL fixture path and stays NOT_RUN.
