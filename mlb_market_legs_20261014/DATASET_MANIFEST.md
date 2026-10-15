# Dataset Manifest — MLB market-leg evaluations (M2/M4 and successors)

Written 2026-10-14, before the M2/M4 runs.

## The corpus

| Field | Value |
|---|---|
| File | `mlb_odds_dataset.json` |
| SHA-256 | `3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b` |
| Size | 80,120,813 bytes |
| Content | 13,121 games under 1,097 date keys; span 2021-04-01 → 2025-08-16; 11,040 regular-season (`gameType == 'R'`) |
| Per-game markets | `odds.moneyline[]`, `odds.pointspread[]`, `odds.totals[]` — per-book entries with `openingLine` and `currentLine`; six books: draftkings, fanduel, caesars, bet365, betmgm, bet_rivers_ny |
| Coverage (all game types) | moneyline non-empty 12,668/13,121; pointspread 12,652; totals 12,652 |
| Timestamps | Game `startDate` only (second precision, all games). **Odds entries carry NO timestamps** — `currentLine` is the source's closing semantics with an undocumented capture instant. Every verdict from this corpus is therefore in the **retrospective-diagnostic evidence class** and does NOT satisfy the PR #2077 strict paired contract. |

## Where the corpus lives — stated plainly

**The corpus is NOT in this repository**, and it is not in any
SportsEdge repository. Verified 2026-10-14 by listing the files of the
pinned tree at `2a713380c7d49733577c238a126f487382634040` (no dataset
file; the only odds-named files are unrelated Odds-API freeze
scripts). At ~80 MB of third-party data with no license granted by its
source, it is not committed.

Local copies held by the research team (byte-identical, both matching
the SHA-256 above):

- `~/workspace/sportsedge/historical_baseline_probes/mlb/mlb_odds_dataset.json` (the copy the evaluators read)
- `~/workspace/sportsedge-backtest/data/mlb_odds_dataset.json`

## Source and acquisition path (for independent reproduction)

- **Source:** GitHub repository `ArnavSaraogi/mlb-odds-scraper`,
  release tag `dataset` (the repo's single release, published
  2025-08-18), release asset `mlb_odds_dataset.json`.
- **Upstream provenance:** the dataset's README states the data was
  scraped from SportsBookReview (SBR). The source repository carries
  **no LICENSE file and no license in its metadata** — no license is
  granted; SBR terms apply. Internal research use only; do not
  redistribute.
- **Acquisition:** the release asset was downloaded on 2026-10-12
  (America/Chicago) into `~/workspace/sportsedge/historical_baseline_
  probes/mlb/` and payload-verified the same day; the verification
  record is `~/workspace/sportsedge/historical_baseline_probes/
  FINDINGS.md` §2 (structure, coverage counts, and the open-vs-close
  distinction were confirmed against the actual payload, including the
  discrepancy that the README claims a 2021-03-20 start while the
  first date key in the file is 2021-04-01).
- **Reproduction check:** after acquiring the file from the source
  above, `sha256sum mlb_odds_dataset.json` must print the SHA-256 in
  the table. If it does not, the dataset in hand is not the dataset
  these verdicts were computed on, and the verdicts do not transfer.

## What is in the repo instead

Everything needed to reproduce the verdicts except the corpus itself:
the specs (with predeclared gates), the evaluators under `scripts/`,
the per-game audit CSVs and results JSONs under
`mlb_market_legs_20261014/`, and this manifest. Each evaluator also
verifies the corpus SHA-256 at load and refuses to score a mismatched
file.
