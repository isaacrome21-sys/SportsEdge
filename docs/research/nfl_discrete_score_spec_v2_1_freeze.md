# NFL discrete v2.1 — family B frozen (2021–2024)

Accepted to land the SHA before Thursday Night Football. Research only.
Attempt 9 stays the live `.5` owner. No phone-card pricing. No M2 bytes.

## Frozen identity

- File: `config/nfl_discrete_v2_freeze.json`
- Family **B**: independent NB scores + lifts on exact margins `{0, ±3, ±7}`
- Fit: NFL REG 2021–2024, n=1087, nflverse `schedules/games.csv`
- `nb_r_home` = 6.998171678749732
- `nb_r_away` = 6.502332860154674
- lifts: `0` = 0.14, `|3|` = 2.7, `|7|` = 1.5
- Home-win-rate baseline (ties not home wins): **0.5400183992640294**

SHA is the canonical dump of the JSON without `artifact_sha256`.

## Holdout

If this freeze is on main before the first 2026 W4 kickoff: **W4–W12**.
If it misses: **W5–W13**. Min n = 80 or `INSUFFICIENT`. One look. No retune.

Gates stay as #1245 v2.1 (outcome frequencies only).
