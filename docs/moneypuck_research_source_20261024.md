# MoneyPuck research source (free CSV downloads)

`scripts/collect_moneypuck.py` is a registered **research/archive**
collector for MoneyPuck's free data downloads. It grants no pricing
role: manifests carry `pricing_input: false` and `play_eligible: false`,
no pricing path imports the collector, and it produces no model
probability. Downloads are hosted on peter-tanner.com, the host the
MoneyPuck data page itself links to.

## Defaults and examples

The default invocation performs **zero network requests**:

```bash
python3 scripts/collect_moneypuck.py teams-history
```

A live archive requires `--live` explicitly and records sha256 of both
the zip and the extracted CSV in a `<name>.manifest.json`:

```bash
python3 scripts/collect_moneypuck.py teams-history \
  --live --out-dir artifacts/moneypuck
python3 scripts/collect_moneypuck.py shots --season 2024 \
  --live --out-dir artifacts/moneypuck
```

Registered datasets: `teams-history`, `skaters-history`,
`goalies-history` (one row per team/player per season per situation),
and `shots --season YYYY` (shot-level rows including `xGoal`).

## Admission evidence (live probe, 2026-10-24)

Row counts are data rows, excluding headers:

| Dataset | File | Rows | Seasons |
|---|---|---:|---|
| teams-history | teams_2008_to_2024.csv | 2,610 | 2008–2024 |
| skaters-history | skaters_2008_to_2024.csv | 76,655 | 2008–2024 |
| goalies-history | goalies_2008_to_2024.csv | 8,020 | 2008–2024 |
| shots 2024 | shots_2024.csv | 119,870 | 2024 only |

Season labels are start years (2024 = the 2024-25 season). Situations
are `all`, `5on5`, `5on4`, `4on5`, `other`; join on `situation = 'all'`
for season totals.

Cross-check vs the NHL official API, EDM 2024-25, situation `all`:
games played 82 = 82 and goals for 259 = 259, exact. Goals against
235 (MoneyPuck) vs 236 (official standings) — shot data does not count
the shootout-deciding goal and EDM lost one shootout that season. This
±1-per-shootout-loss convention gap is expected on any join between
the two sources.

## Limits

- The one-row-per-season rollups end at season 2024 (2024-25) as of the
  probe; the current season is only available in MoneyPuck's
  game-by-game player zips, which are a different grain and are **not**
  registered here.
- Files are large (skaters history ≈ 57 MB uncompressed; a single
  shots season ≈ 69 MB). The collector streams one dataset per run and
  archives the CSV as-is; nothing is sampled or filtered.
- MoneyPuck is a one-person research site with no SLA; the zip member
  name is verified exactly and the collector fails closed if the
  archive layout changes.
