# NBA / MLB Analytics Wiring Matrix — true state, verified 2026-10-28

Repo: isaacrome21-sys/SportsEdge · Base main: `6eedf825eb3712de3e1caa676c71581684d9c7f8`
Method: every row grounded in a file read or a search executed in this pass.
Full-tree term checks used the GitHub code-search index over main (executed
2026-10-28, before that API's quota exhausted); local greps covered
`sportsedge/ scripts/ config/ data/ docs/ research/ tests/` + all three
dependency manifests. The two methods agree on every overlapping term.

State vocabulary: **WIRED** = engine code consumes it · **ADMITTED-NOT-WIRED**
= an in-repo admission/registry record exists but no engine consumer ·
**REACHABLE-ONLY** = library/endpoint present but not declared or not consumed
by any engine path · **ABSENT** = no in-repo trace.

## NBA

| Source | State | Evidence |
|---|---|---|
| SportsDataverse data releases (nba_stats_player_boxscores) | **WIRED** | `scripts/pull_nba_results.py` pulls `player_boxscores_{season}.csv` from `sportsdataverse/sportsdataverse-data` GitHub release assets (retry/backoff contract); training-side consumer `sportsedge/sports/nba/sportsdataverse_training_source.py`. This — not hoopR-the-package — is the repo's actual NBA box-score wire. |
| ESPN (NBA availability/identity) | **WIRED** (verification role) | `sportsedge/sports/nba/espn_verified_source.py` exists in the engine package. (Role per module name/packaging; contents not line-audited in this pass.) |
| nba_api / stats.nba.com | **ABSENT** (tried, abandoned) | Zero imports anywhere; code search `stats.nba.com` = 0. `scripts/pull_nba_results.py` docstring records the live nba_api path failing four consecutive times from GitHub runners (runs 39189944292, 39190353182, 39191026493) and being replaced by the SportsDataverse asset. Not in any manifest. |
| {nbadatar} / shufinskiy/nba_data | **ABSENT in-repo** | Code search total_count = 0 for both `nbadatar` and `shufinskiy`. A program-level "admitted Oct 21 as cross-check" claim exists only in workspace planning documents (gap-fill plan §3.3) — there is **no repo artifact, registry entry, fetcher, or consumer**. Any earlier report calling this ADMITTED described a paper decision that never landed in the repo. If the cross-check is wanted, it needs a real admission record + fetcher PR. |
| hoopR (R package) | **ABSENT** | Code search `hoopR` = 0; no R code or R dependency anywhere. (Its data publisher, SportsDataverse, is wired — see row 1. Do not conflate the two.) |
| Basketball-Reference | **ABSENT** | Code search `basketball-reference` = 0. |
| NBA.com/stats endpoints | **ABSENT** | Same evidence as nba_api row (one endpoint family). |
| RAPM family (nbarapm.com / databallr.com) | **ABSENT** | Code search = 0 for both domains. nbarapm.com does publish a datasets index (verified live 2026-10-28: /datasets, /datasets/nba, /datasets/comp) — a wiring candidate, not a wired source. |
| Dunks & Threes EPM | **ABSENT** | Code search `dunksandthrees` = 0. Live probe 2026-10-28: the /epm page is a client-rendered app whose static HTML contains **no embedded EPM data** — no stable CSV/JSON endpoint was identified. Wiring it tonight would mean scraping a JS app; not small, not clean (see Deliverable-3 note). |
| StatMuse | **ABSENT** | Code search `statmuse` = 0. |
| Kaggle NBA odds archive (adjacent, not analytics) | **WIRED** (odds, not performance data) | `scripts/archive_kaggle_nba_odds.py` + `sportsedge/backtest/kaggle_nba_baseline.py` exist on main (schema-fixed in draft PR #2834). Listed so nobody mistakes odds coverage for analytics coverage. |

**NBA summary:** exactly one performance-data wire exists — SportsDataverse
release assets for player box scores — plus an ESPN verification module.
Every advanced/impact source (RAPM, EPM, Basketball-Reference, NBA Stats)
is absent. The nbadatar "admission" is a paper claim with no repo footprint.

## MLB

| Source | State | Evidence |
|---|---|---|
| MLB StatsAPI (statsapi.mlb.com) | **WIRED** (primary) | Engine consumption across the stack: `sportsedge/backtest/outcomes.py`, `sportsedge/canonical_manual_mlb.py`, `sportsedge/dfs/sources/mlb_statsapi.py` (BASE v1 + LIVE_BASE v1.1), `sportsedge/live_poll.py`, `sportsedge/live_state.py`, `sportsedge/mlb_all_market_features.py`, `sportsedge/mlb_bullpen_workload_source.py`, `sportsedge/free_factors.py`. |
| Baseball Savant Statcast CSV (baseballsavant.mlb.com/statcast_search/csv) | **WIRED** (own raw implementation) | `sportsedge/mlb_savant_features.py` implements chunked fetches with explicit guards against Savant's 25k-row silent truncation; consumed by `sportsedge/mlb_hr_prop_model.py` and `sportsedge/prepricing/factor_ingestion.py`. Registered in `sportsedge/tracking_source_registry.py` as `BASEBALL_SAVANT_STATCAST_CSV`, module `sportsedge.statcast_daily_source`, noted "already wired in main"; registry policy line: new Statcast-flavored acquisition must use `MLB_STATSAPI_PITCH_TRACKING`. |
| Statcast via pybaseball | **REACHABLE-ONLY** | Exactly **one** import in the repo: `scripts/refresh_statcast_daily.py` line 9, `from pybaseball import statcast` (a research refresh script, no pricing-path consumer). `scripts/collect_statcast_research.py` mentions pybaseball only in a comment. **pybaseball is an UNDECLARED dependency** — absent from `pyproject.toml`, `requirements-test.txt`, and `requirements-research.txt` (research manifest contains only playwright). Any fresh environment running that refresh script fails on import. |
| FanGraphs | **ABSENT** | Code search `fangraphs` = 0 — no scraping, no pybaseball FanGraphs calls. |
| Retrosheet (event files 2022–2024) | **WIRED-BY-DERIVATION — NOW PINNED** | Inputs were never committed/hashed/dated; the derived table `data/component_park_factors_2022_2024.json` is loaded by the factor layer (`sportsedge/free_factors.py` `component_park`, `sportsedge/mlb_hr_prop_model.py`, `sportsedge/mlb_total_bases_features.py`). Pinning pass 2026-10-28: downloaded the three annual zips from retrosheet.org, sha256-recorded them, re-ran `scripts/derive_component_park_factors.py` unmodified — output is **byte-identical** to the committed JSON (sha256 `512c89c9d5eda59eff0305a2dc1320bef1701b12706ddf4e3bd21d1b00a31309` both sides; all 180 team×component cells equal). Verdict: **MATCH**. Full record in the companion pin document. |
| Lahman database | **ABSENT** | Zero references to the database in code/docs/config/data. The only `lahman` strings in the repo are the unrelated GitHub username `blaizerlahman` (a CFB project) in `sportsedge/sports/cfb/public_mirror.py` and `config/model_improvement_backlog_v1.json`. Reachable only as an unused submodule of the undeclared pybaseball install. |
| Chadwick tooling | **ABSENT** | Zero references; the Retrosheet derivation parses event files with its own regex classifier (`scripts/derive_component_park_factors.py`). |

**MLB summary:** StatsAPI is the load-bearing wire and Savant is genuinely
wired through an in-repo implementation — the analytics stack is in far
better shape than NBA's. The one live defect is the undeclared pybaseball
import in a scheduled refresh script.

## Proposals (not unilateral changes)

1. **pybaseball:** either declare it in `requirements-research.txt`
   (one line, parity-safe: research manifest is outside the test-parity pair)
   or migrate `scripts/refresh_statcast_daily.py` onto the in-repo Savant /
   StatsAPI pitch-tracking path the tracking registry already mandates.
   Leaving an undeclared import in a refresh path is a when, not an if.
2. **nbadatar/shufinskiy:** if the Oct 21 cross-check decision still stands,
   land it properly — admission record + pinned fetcher + a named consumer —
   or strike the claim from planning docs. Paper admissions that never reach
   the repo are how "wired" rots into fiction.
3. **EPM/RAPM:** first wiring candidates when NBA current-form inputs are
   built. nbarapm's datasets index is the cleaner entry point; EPM needs an
   endpoint discovery pass against the live app before any fetcher is written.

## Freeze-coverage check

Paths this work would touch — `research/nba_mlb_analytics_wiring_20261027/`,
`research/retrosheet_park_factor_pin_20261027/`,
`data/component_park_factors_2022_2024.provenance.json` — were checked against
all 11 bundles in `config/freeze_reconciliation_registry_v1.json`
(prefixes + exact paths). **None is governed.** No committed park-factor
values are changed by this work; the pin adds provenance only.

*Research only. PAPER / 0u. No betting authority.*
