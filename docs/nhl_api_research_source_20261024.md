# NHL official API research source (api-web.nhle.com)

`scripts/collect_nhl_api.py` is a registered **research/archive** collector
for the NHL's official public API. The API is free and needs no key. This
registration grants no pricing role: envelopes carry `pricing_input: false`
and `play_eligible: false`, no pricing path imports the collector, and it
produces no model probability. It exists so NHL schedule, score, standings,
and club-stat archives accumulate under one provenance label.

## Defaults and examples

The default invocation performs **zero network requests** and prints the
planned URL:

```bash
python3 scripts/collect_nhl_api.py score --date 2026-10-23
```

A live snapshot requires `--live` explicitly:

```bash
python3 scripts/collect_nhl_api.py standings --date 2025-04-17 \
  --live --out-dir artifacts/nhl_api
python3 scripts/collect_nhl_api.py club-stats --team EDM \
  --season 20242025 --game-type 2 --live --out-dir artifacts/nhl_api
```

Registered endpoint kinds: `standings` (dated, or `now`), `score/{date}`,
`schedule/{date}`, `club-stats/{team}/{season}/{gameType}` where gameType
1 = preseason, 2 = regular season, 3 = playoffs.

## Admission evidence (live probe, 2026-10-24, from the build sandbox)

- `standings/now` answers 307 → `standings/2026-10-24` (32 teams).
  Standings by date verified back to 2000-04-08 (28 teams returned);
  club stats verified back to season 20102011. No key, no 401/403 seen.
- A burst of 30 sequential requests produced 30 × HTTP 200 and no 429;
  no published rate limit was encountered. Collectors should still run
  serialized, one endpoint per invocation.
- Cross-check, NHL vs ESPN scoreboard, completed games: **14/14 final
  scores agreed exactly** (12 games on 2026-10-22, 2 on 2026-10-23).
  ESPN abbreviates SJ/NJ/LA where the NHL uses SJS/NJD/LAK — a naming
  difference only; scores matched per team after mapping.
- Known semantic difference: official standings goals-against counts the
  shootout-deciding goal; shot-derived sources (e.g. MoneyPuck) do not.
  EDM 2024-25: API GA 236 vs MoneyPuck 235, and EDM's shootout record
  that season was 0W-1L. Treat standings GA as the official figure and
  expect ±1 per shootout loss when joining against shot data.

## Limits

- This is the league's public web API, not a contracted feed: no SLA,
  no published rate limit, and payload fields can change without notice
  (the collector fails closed on non-JSON or non-object bodies).
- `score` rows for games not yet started carry `null` scores; consumers
  must key on `game_state`, not on score presence.
- Standings snapshots are point-in-time: a dated request returns that
  date's table, which is the correct input for historical joins.
