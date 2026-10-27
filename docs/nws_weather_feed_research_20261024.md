# NWS weather feed — registered research source

`sportsedge/nws_weather_source.py` + `scripts/collect_nws_weather.py` register
the **National Weather Service API** (`api.weather.gov`) as a research data
source: the live feed behind the declared weather thresholds in
`sportsedge/free_factors.py` (`weather_total_adjustment` / `ingest_weather`).
Those thresholds remain **PENDING_VALIDATION** and this feed changes nothing
about them: the collector is not imported by any pricing path, computes no
adjustment, and every record it emits is labeled `research_only`,
`validation_status: PENDING_VALIDATION`, `pricing_impact: NONE`,
`staking_allowed: false` on its face.

This is the cross-sport observation/forecast source. It complements, and
does not replace, `sportsedge/mlb_weather_roof_source.py` (MLB-specific
NWS roof/grid context) and the Open-Meteo provider path used elsewhere.

## Source facts (live-probed 2026-10-24)

- Free public API. **No key, no account.** A descriptive `User-Agent`
  header is required; the collector sends one.
- `GET /points/{lat,lon}` resolves the forecast office/grid, the hourly
  forecast URL, and the observation-station list (nearest first).
- Observations are per-station, newest-first, **cursor-paginated**; a
  first page can end before the requested window start, so the collector
  walks cursors (bounded at 5 pages) until the window start is covered,
  then re-filters by window regardless of what pages returned.
- Observation units: whole-degree °C temperature, km/h wind, degree wind
  direction, free-text conditions. `precipitationLastHour` is frequently
  **null** — the collector preserves null as missing, never zero.
- Any venue is just a latitude/longitude: NFL, CFB, MLB, and NHL venues
  are all in scope of the same code path. Venue roof state is **not**
  modeled — a domed or retractable venue still returns outdoor weather;
  venue→roof mapping is a follow-up, not part of this registration.

## Command

```bash
python3 scripts/collect_nws_weather.py \
  --lat 30.285 --lon -97.732 \
  --start 2026-10-24T23:30:00Z --end 2026-10-25T02:30:00Z \
  --out artifacts/nws_weather/texas_olemiss_20261024.json
```

Exit 0 with a record whose `status` is `VERIFIED_OBSERVATION` or
`UNVERIFIED` (a data verdict, not a failure); exit 2 on transport/contract
failure, with no record fabricated.

## What is saved

One JSON record per call: normalized game-window weather (temperature °F,
dewpoint °F, wind mph + degrees + compass, last-hour precipitation mm,
conditions text), the overlapping hourly-forecast periods, and provenance
(forecast office/grid, every station tried, per-station errors, the
winning station and its `observed_at`).

Fail-closed rules:

- An observation counts only **inside** the requested window, never from
  the future relative to retrieval time, and only within **90 minutes**
  of the window start; otherwise the record is `UNVERIFIED` with a named
  reason (`NO_OBSERVATION_IN_WINDOW` /
  `OBSERVATION_STALE_AT_WINDOW_START`) and null observation fields.
  Nothing is interpolated or carried over.
- Every tried station is evaluated; the observation closest to the
  window start wins (a nearer station's old report cannot shadow a
  fresher one).
- A measured value whose unit code is not the expected WMO unit is
  treated as missing, never silently reinterpreted.
- Transport/JSON failure on the points or stations lookups raises
  `NWSWeatherSourceError` — no record is fabricated.

## Admission probe evidence (2026-10-24, Austin TX)

Points for Darrell K Royal–Texas Memorial Stadium (30.285, -97.732)
resolved to office **EWX**, grid **156,92**, stations KATT (Camp Mabry),
KAUS (Austin-Bergstrom), KEDC, and a live hourly forecast.

**Cross-check** — Texas vs Ole Miss kickoff window (kickoff 18:30 CT =
23:30 UTC, 2026-10-24), independently reported game conditions:
*Sunny, 84°F, wind SE 10 mph*. The collector returned KAUS at
**23:35 UTC** (5 minutes after kickoff): **82.4°F** (28°C), wind
**8.1 mph at 130° (SE)**, conditions **Clear**, precipitation null.

- Conditions: Clear vs Sunny — agreement (station text vs daytime wording).
- Wind direction: SE vs SE — agreement.
- Wind speed: 8.1 mph vs 10 mph — the feed figure sits inside the
  8.1–11.5 mph range KAUS reported across 23:25–23:40 UTC; consistent
  with a rounded snapshot.
- Temperature: **82.4°F vs 84°F — a named 1.6°F discrepancy, not smoothed.**
  NWS stations report whole °C (28°C here) and KAUS sits ~8 miles from
  the stadium; either explains part of it, neither is assumed.

## Limits

- Hourly-station cadence varies (KATT reports hourly, KAUS every
  ~5 minutes), and individual reports go missing (KATT had no 23:51 UTC
  report) — the 90-minute lag bound is what keeps a thin station from
  silently describing kickoff with an old report.
- Forecast periods are the *current* hourly forecast; NWS does not serve
  historical forecast vintages through this API, so a post-game pull
  cannot reconstruct what the forecast said before kickoff. Only the
  observation side is point-in-time evidence after the fact.
- Whole-°C observation precision bounds temperature resolution to
  ~1.8°F steps.
