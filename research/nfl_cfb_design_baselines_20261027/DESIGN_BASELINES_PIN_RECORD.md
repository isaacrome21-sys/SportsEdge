# NFL / CFB DESIGN baselines — pin record (2026-10-27)

**Status: DESIGN ONLY.** This record pins two historical datasets as *design*
baselines for future construction work, per
`VERIFIED_MODELS_GAP_FILL_PLAN_20261027.md` (recommended admission #3) and build
order items 3 (NFL successor design pack) and 4 (CFB G3 admissibility audit).

**Branch base main:** `bc00a6106317d265e3d03c061915d37a2c08c2c8`
**Retrieval:** 2026-10-27 22:55 CDT (2026-10-28T03:55:17Z), by the overnight
build pass. Reproduce with `fetch_design_baselines.py` in this directory.

## Standing labels (read first — these bind every use of this data)

- **DESIGN ONLY — never validation evidence.** Historical data already seen by
  FAILED constructions (NFL sides/totals incumbents and NFL_ANCHORED_RATINGS_V1;
  CFB PM / AM / PRIOR_CURRENT_BLEND / CFB_CONVERGED_ANCHOR_V1) is design data,
  not validation data. FAILED constructions stay retired; nothing in this record
  resurrects them or re-runs their screens as if the evidence were new.
  Verification accrues forward only — **no backfill, ever**.
- **No verified CLV from these closes.** Owner ruling (Isaac, Oct 26, 2026):
  CFB reporting shows actual results including failures; the flat −110 ROI is
  an ASSUMPTION and must be labeled as such; **comparisons against the
  untimestamped SDV closes must NEVER be labeled verified CLV.** The same rule
  applies to the nflverse closing snapshot (Gap G7): it carries no quote
  timestamps, so vs-close against it is never verified CLV either.
- **No clock or counting claim.** This record starts nothing, counts nothing,
  and changes no gate, threshold, frozen term, or prereg.
- **PAPER / research only.** No staking or wager execution is authorized by
  anything in this record.

## Dataset 1 — nflverse schedules (closing snapshot + QB/context fields)

- **Status: HASH-VERIFIED BY ACTUAL PULL** (this pass).
- **Source:** nflverse / nflverse-data, GitHub Releases —
  `https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv.gz`
- **Committed file:** `nflverse_games.csv.gz` (the full release file, 516 KB —
  small enough to pin whole rather than subset).
- **SHA-256:** `82b05d7096b3f59acd127da8762b1e2260f4af70b49e5548ce4cd3ade92a49a5`
- **Bytes:** 515,925 · **Rows:** 7,548 games · **Columns:** 46
- **Coverage:** seasons **1999–2026** (2026 in progress at pull time).
  Per-era completeness, verified from the pulled bytes: spread_line and a
  recorded starting QB are present for **every** row in 1999–2012 (3,714),
  2013–2019 (1,869), and the design seasons 2020–2025 (1,693); the partial
  2026 season has 272 rows, 136 with a spread_line and 121 with a QB (games
  not yet played).
- **Fields this pin exists for** (verified present in the pulled header):
  `spread_line`, `total_line`, `away_moneyline`, `home_moneyline`,
  `away_spread_odds`, `home_spread_odds`, `over_odds`, `under_odds`,
  `away_qb_name`, `home_qb_name` (recorded starting QBs), `away_rest`,
  `home_rest`, `roof`, `surface`, game-time `temp` / `wind`, coaches,
  referee, stadium.
- **Admission class:** one closing snapshot per game — **no quote
  timestamps** → design/screen baseline only (plan §3.1, Gap G7).
- **Known gaps / leak classes:**
  - The recorded QB is the QB who *actually* started (post-hoc identity), not
    a pre-kickoff designation. Named residual leak class: game-time scratches
    where the market priced a different expected starter. Any screen using
    the QB fields must handle this by sensitivity exclusion.
  - No pre-1999 seasons in this release.
  - The 2026 season is partial and accrues; a successor design pack must
    re-pin rather than silently absorb new rows.
- **Seen before?** Yes — nflverse design seasons 2020–2025 were seen by
  retired NFL constructions. Design-only for any successor.
- **Cost / license:** free, no key. Package code MIT; data subject to upstream
  providers' terms (PFR / NFL / FTN).

## Dataset 2 — CollegeFootballData (CFBD) betting lines, 2013+

- **Status: DOCUMENTED ONLY in this pass — not hash-verified by pull.**
  **Blocker (one line):** the CFBD key (env) was not present in this build
  environment (checked `SPORTSEDGE_CFBD_API_KEY`, `CFBD_API_KEY`,
  `CFB_SDV_CFBD_API_KEY`); the API answers 401 unauthenticated, so no bytes
  were pulled and no hash is claimed. The key's value is never printed,
  written, logged, or committed anywhere — `fetch_design_baselines.py` reads
  it from the environment only. Run the script in an environment where the
  key is present to complete the hash-verified pin; its output drops into
  `PINS.json` unchanged.
- **Source:** CollegeFootballData API — `https://api.collegefootballdata.com/lines`
  (per-year query `?year=YYYY`), accessed via the API directly (same data the
  `cfbd` Python / `cfbfastR` R loaders wrap).
- **Documented contents** (from the plan's Oct 27, 2026 verification of the
  `cfbd_betting_lines` documentation, §3.2): betting lines and ATS records,
  **2013–present** — per game and provider: closing **and** opening spread,
  closing **and** opening total, home/away moneylines; providers include
  Caesars / consensus / numberFire / teamRankings.
- **Admission class:** open/close snapshots carry **no quote timestamps** →
  design baseline only, exactly as the Oct 26 SDV-closes evaluation treated
  them (labels: flat −110 = assumption; vs-close ≠ verified CLV). This is the
  market baseline the failed CFB constructions already faced — **seen data,
  design-only**.
- **Known gaps:**
  - Provider coverage varies by game and season; not every game carries every
    provider, and some games carry no line at all. (To be quantified from the
    actual pull when the pin completes — not estimated here.)
  - CFBD has **no pre-kickoff starting-QB designation feed** (Gap G3):
    rosters + player game stats identify who played, not who was designated
    pre-game. This dataset does **not** cure G3; the G3 admissibility audit
    (plan build order #4) still decides whether any CFB sides/totals
    successor may be designed at all.
- **Illinois college exclusion (scope note):** CFB modeling scope excludes
  Illinois *college* teams, as with the existing CFB exclusion mechanism;
  Illinois professional teams are unaffected and in scope. The exclusion
  applies at modeling/screen time — this pin records the raw national
  baseline unfiltered so the design packs stay auditable.
- **Cost:** free API key (the program already holds one; value never printed).

## Freeze-coverage check

Both new paths were checked against every bundle's `coverage_paths` /
`coverage_prefixes` in `config/freeze_reconciliation_registry_v1.json` on the
branch base: **not governed** — no bundle covers
`research/nfl_cfb_design_baselines_20261027/`. No config, registry, workflow,
or engine path is touched by this PR. No dependencies were added (the fetch
script is standard-library only), so the pyproject/requirements-test parity
gate is unaffected; the script passes the ruff gate select
E9,F821,F822,F823,F811.

## What this record does not do

- It does not admit either dataset as a validation baseline, a close for CLV,
  or evidence for any verdict.
- It does not start, arm, or alter any forward clock, screen, or freeze.
- It does not design the NFL successor construction or run the CFB G3 audit —
  it pins the inputs those two work items will cite.
