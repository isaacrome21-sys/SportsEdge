# Keyed Archival Integrations — Setup & Dispatch Guide

## Status: secrets are LIVE, workflows are dispatch-ready on merge

Isaac confirmed Oct 11 (~8:00 PM CT): all three secrets are now set in the
repo's GitHub Actions secrets. **There is no setup step left.** Once this
branch merges to `main`, both workflows run as configured below. (Secret
names are listed for audit only — values are never handled here, never in
chat, never in code.)

| Secret name | Source | Status |
|---|---|---|
| `SPORTSEDGE_CFBD_API_KEY` | collegefootballdata.com/key (free tier) | LIVE |
| `SPORTSEDGE_KAGGLE_USERNAME` | Kaggle account API token (`kaggle.json` → `username`) | LIVE |
| `SPORTSEDGE_KAGGLE_KEY` | Kaggle account API token (`kaggle.json` → `key`) | LIVE |

Code reads these from the environment only, fails closed when absent, and
never prints/logs/embeds the values (verified in unit tests: fake values
asserted absent from every error path).

## Dispatch step for Isaac (first run after merge)

Both workflows are safe to trigger manually the first time — scheduled
runs then take over. Go to the repo → **Actions** tab → pick the workflow
→ **Run workflow**:

1. **`archive-cfbd-advanced`** — mode `backfill`, years `2022`–`2025`.
   One-time historical fill: ~124 CFBD calls (well under the 1,000/month
   free tier). Completed seasons are immutable and never re-pulled.
   After the backfill, the weekly Tuesday schedule keeps the current
   season fresh at ~4 calls/run.
2. **`archive-kaggle-nba-odds`** — default dataset
   `cviaxmiwnptr/nba-betting-data`. Downloads (CC0), normalizes to the
   stable schema, archives per-season CSVs + manifest on the `data`
   branch. Monthly schedule thereafter.

Watch the first run's logs for `ARCHIVED` (or `FAILED_CLOSED` with a
reason — e.g. `KAGGLE_AUTH_FAILED` would mean a secret needs re-pasting;
`CFBD_BUDGET_*` would mean the month's budget is spent).

## What the workflows do (steady state)

**CFBD (college football advanced stats)** — `archive-cfbd-advanced`,
Tuesdays 08:00 CT:
- Pulls only what's missing: the current season's `/stats/season/advanced`
  (raw EPA, success rate, havoc, PPA — 1 call) plus the latest completed
  week not yet archived (`/stats/game/advanced` + `/ppa/games` — 2 calls),
  plus 1 call to `GET /info` for tier/budget discovery.
- Data lands on the `data` branch under `archive/cfb-advanced/`; the phone
  runner reads it via `sportsedge/cfbd_reader.py` and **never calls the
  CFBD API itself**.
- SP+ is deliberately NOT wired: it's a paid-tier, opponent-adjusted
  product. We archive the free raw numbers and compute our own opponent
  adjustment (two-way fixed-effects least squares over per-game EPA, as-of
  by week, zero-sum margin pinning — documented in
  `sportsedge/cfbd_reader.py`).

**Kaggle NBA odds (market-baseline leg)** — `archive-kaggle-nba-odds`,
1st of each month:
- Downloads `cviaxmiwnptr/nba-betting-data` via the Kaggle API (HTTP Basic
  auth from the two secrets; stdlib only, no CLI dependency), normalizes
  raw columns to the canonical schema, verifies spread orientation
  empirically (moneyline-favorite agreement ≥95%, else fail closed), and
  archives per-season CSVs + manifest under `archive/nba-kaggle-odds/`.
- Feeds the backtest harness's **market-baseline comparison only**. Never
  a pricing input — market-blind stands.
- Drop-in loader: `sportsedge/backtest/kaggle_nba_baseline.py`
  (`KaggleNbaBaseline`) implements the harness's `BaselineSource`
  contract; integration diff for `market_baseline.py` is in its docstring.

## Call-budget math (CFBD — the binding constraint)

| Item | Calls | Cadence |
|---|---|---|
| GET /info (tier + remaining budget discovery) | 1 | every run |
| /stats/season/advanced (all teams, one season) | 1 | weekly (skipped if archived) |
| /stats/game/advanced (one week) | 1 | weekly, latest completed week only |
| /ppa/games (one week) | 1 | weekly, latest completed week only |
| **Steady-state weekly total** | **~4** | **~16–20/month of 1,000** |
| Backfill 2022–2025 (one-time) | ~124 | manual dispatch only |
| Play-by-play | 0 | not scheduled (dispatch-only probe, capped) |
| Free-tier monthly limit | 1,000 | calendar-month reset, pool shared with CFBD basketball |

The script refuses to run when the plan exceeds the remaining budget
reported by CFBD itself — it checks `/info` first, every run, and never
hardcodes the limit. A durable ledger lives at
`runtime/cfbd-budget/ledger.json` on the data branch. `workflow_dispatch`
inputs (`mode`, `year_start`, `year_end`, `max_calls`) let Isaac bound any
manual run explicitly.

## Verification (all local, no keys, no network)

- `python -I scripts/archive_cfbd_advanced.py --self-test`
- `python -I scripts/archive_kaggle_nba_odds.py --self-test`
- `python -m pytest tests/test_cfbd_client.py tests/test_archive_cfbd_advanced.py tests/test_cfbd_reader.py tests/test_archive_kaggle_nba_odds.py tests/test_kaggle_nba_baseline.py -q` — 49 passed

## Adding another Kaggle dataset later

1. Add an entry to `DATASET_REGISTRY` in
   `scripts/archive_kaggle_nba_odds.py`: owner/slug, archive subdir,
   column aliases, spread-perspective (or `None` for empirical
   verification), provenance notes.
2. Run the workflow with the `dataset` input set to the new slug (or add a
   matrix leg in `archive-kaggle-nba-odds.yml`).
3. The normalizer fails closed with the observed header if the publisher's
   schema doesn't match the registered aliases — last-good data stays in
   place; nothing silently mis-maps.

## Known limitations

- **CFBD opponent adjustment is ours, not theirs.** CFBD's own adjusted
  metrics are paid-tier; our least-squares adjustment over raw per-game
  EPA is documented in `sportsedge/cfbd_reader.py` and is harness-gated
  like every other factor (it proves itself in the backtest before
  touching pricing). When a sample's game graph is bipartite, the audit
  flags `offense_defense_split_identified: false` — consume margins only.
- **Kaggle NBA is soft consensus-close.** No free sharp (Pinnacle)
  open+close dataset exists for NBA; the harness baseline verdict stays
  CONDITIONAL per spec. This fills the leg — it doesn't upgrade it.
- **Raw Kaggle schema is publisher-controlled.** The normalizer maps it to
  our stable schema with an explicit alias table and fails loudly (with
  the observed header in the log — column names are not secrets) if the
  publisher changes columns.
- **Play-by-play is intentionally out of the scheduled pull.** At ~70
  calls per FBS week it would eat the budget; the per-game EPA/PPA
  aggregates cover the model inputs. Revisit only if the harness shows a
  gap that play-by-play provably fills.
- Keys work Actions-side only. If a workflow fails with
  `CFBD_KEY_MISSING` / `KAGGLE_CREDENTIALS_MISSING`, a secret got deleted
  or renamed — re-adding it in repo settings is the only fix.
