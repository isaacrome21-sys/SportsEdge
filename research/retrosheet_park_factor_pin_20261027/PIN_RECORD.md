# Retrosheet Pin Record — component park factors 2022–2024

Date of pass: **2026-10-28** · Repo base: `6eedf825eb3712de3e1caa676c71581684d9c7f8`
Subject artifact: `data/component_park_factors_2022_2024.json`
Derivation: `scripts/derive_component_park_factors.py` (unmodified)

## The gap this closes

The committed park-factor table was derived from Retrosheet annual event
zips that were **never committed, never hashed, and never dated**. From the
repo alone, the derivation was unreproducible: Retrosheet revises event
files over time (its Summer 2026 release alone updated 14,631 games), so a
re-download could silently differ from whatever the factors were built from.

## Inputs retrieved and pinned (2026-10-28T04:44:31Z)

Source: Retrosheet event-file downloads, linked from
https://www.retrosheet.org/game.htm (per-season regular-season event files).

| File | URL | Bytes | sha256 |
|---|---|---|---|
| 2022eve.zip | https://www.retrosheet.org/events/2022eve.zip | 2,497,692 | `cce73b21bed02283eb70f95e18575f4c8b60b968c75f926530b43f35c85f4c61` |
| 2023eve.zip | https://www.retrosheet.org/events/2023eve.zip | 2,532,820 | `301e6d36afd58f3c2f9b3dfa546cb7953b24c90a4de57a69565ccc2f2a5eb8d1` |
| 2024eve.zip | https://www.retrosheet.org/events/2024eve.zip | 2,674,738 | `5dfd9ed678c9c619f6a216322922c99234c067d0ec15b12790546f620ced2fa4` |

Unzipped contents: 183 event files (`{season}{TEAM}.EVA/.EVN`), parsed by the
derivation at **7,289 games**, 30 teams.

## Re-derivation result — MATCH

Ran the repo's own script, unmodified, against the pinned inputs:

```
python3 scripts/derive_component_park_factors.py \
  --data-dir <unzipped events> --seasons 2022,2023,2024 --out rederived.json
```

| Check | Result |
|---|---|
| Team set | identical, 30 / 30 |
| Component cells (30 teams × 6: 1B, 2B, 3B, HR, BB, K) | **180 compared, 0 differing** (pf, raw, home_pa all equal) |
| Metadata block (schema, source, seasons, method, regress_pa, research_only) | identical |
| File bytes | **identical** — committed sha256 `512c89c9d5eda59eff0305a2dc1320bef1701b12706ddf4e3bd21d1b00a31309` = re-derived sha256 `512c89c9d5eda59eff0305a2dc1320bef1701b12706ddf4e3bd21d1b00a31309` |

**Verdict: MATCH.** The committed factors are exactly what the pinned
Retrosheet inputs produce under the committed derivation. The provenance pin
therefore applies retroactively with full evidence: any future re-run from
these three zips must reproduce the committed table bit-for-bit, and any
future Retrosheet revision to the 2022–2024 event files will show up as a
hash change at the zip level before it can silently move a factor.

## What this pin does NOT do

- It does not change any committed factor value (none needed changing).
- It does not commit the zips to the repo (7.7 MB of third-party data;
  Retrosheet's own notice permits any use with attribution — the hashes +
  URLs above are the reproducible pointer).
- It does not extend the table past 2024. The derivation's fail-closed rule
  for 2025+ (A's/Rays park changes) stands untouched.

## Machine-readable companion

`component_park_factors_2022_2024.provenance.json` (prepared alongside this
record, proposed placement beside the artifact at
`data/component_park_factors_2022_2024.provenance.json`) carries the same
pins in JSON for automated checks.

## Freeze-coverage check

`research/retrosheet_park_factor_pin_20261027/` and
`data/component_park_factors_2022_2024.provenance.json` were checked against
all 11 bundles in `config/freeze_reconciliation_registry_v1.json`.
**Neither path is governed.** No frozen terms, thresholds, or factor values
are touched.

*Research only. PAPER / 0u. Retrosheet data used free of charge from
retrosheet.org; attribution per Retrosheet's notice.*
