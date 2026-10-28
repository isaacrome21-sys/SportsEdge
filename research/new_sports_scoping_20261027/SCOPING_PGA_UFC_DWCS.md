# New-Sports Data Scoping — PGA · UFC · DWCS

**Date:** Oct 27, 2026 (America/Chicago). **Authority:** owner ruling Oct 27, 2026 ~23:04 CT
("Nothing is paused anymore. We're going all out nba nfl CFB cbb nhl pga ufc DWCS GO") adding PGA,
UFC, and DWCS to the SportsEdge program.
**Status of this document:** scoping only. No source in it is admitted, no construction is
preregistered, and nothing here is verified. Under the standing law as amended Oct 27, 2026,
VERIFIED = a construction that has passed its preregistered chronological out-of-sample
validation against BOTH the existing model and a contemporaneous market baseline. Every claim
below is labeled with its evidence state: *verified by pull/page this session*, *repo record*,
or *documented-only*.

**Freeze-coverage check:** this path (`research/new_sports_scoping_20261027/`) was tested
programmatically against all 11 bundles in `config/freeze_reconciliation_registry_v1.json`
(coverage paths + prefixes). **Not governed.** No config, registry, workflow, or engine path is
touched by this document.

---

## 0. What already exists in the repo (do not rebuild)

These sports are not greenfield. An earlier program era (Aug–Sep 2026) built real scaffolding,
all present on current main (318377dfa) — *repo record, read firsthand this session*:

| Sport | Existing assets | Existing status (repo's own words) |
|---|---|---|
| PGA | `sportsedge/pga_engine.py`; `sportsedge/pga/` package (joint field simulation: outright, first-round leader, top-K, make-cut, H2H; live model with long-term-skill prior + bounded form/course-fit/weather refinements); `config/pga_benchmark_methodology.json` (**frozen** benchmark contract: N-way markets use full-field multiplicative de-vig, TOP_K/MAKE_CUT are binary per golfer with paired YES/NO, H2H paired two-way with pushes tracked); `config/pga_market_surface.json`; `docs/PGA_MODEL_STATUS.md` | **No PGA market family is promoted.** `automatic_input_acquisition_complete: false` — the engine consumes hand-built snapshot files; **automated data acquisition is the open gap.** Weights are "model hypotheses, not a claim of out-of-sample superiority." |
| UFC | `docs/ufc_model_design.md` (pre-fight probabilities from UFCStats snapshots strictly before bout time; calibrated logistic + gradient-boosted challenger + Elo prior; walk-forward only; log loss/Brier/calibration + closing no-vig baseline; truth gate); `sportsedge/ufc_source.py`, `ufc_history.py`, `ufc_training.py`, `ufc_engine.py`, `ufc_promotion.py`, `ufc_runtime.py`; `scripts/build_ufc_training_artifact.py`, `build_ufc_live_inputs.py`, `run_ufc_full_model.py`; `.github/workflows/ufc-full-model.yml`; `config/ufc_market_surface.json`, `config/ufc_promotion_contract_v1.json` | Market surface supports **MONEYLINE_H2H only**; METHOD_OF_VICTORY, ROUND_OF_VICTORY, TOTAL_ROUNDS, FIGHT_GOES_DISTANCE, WIN_BY_KO/SUB/DEC are all `unsupported_without_new_engine`. Training artifact self-reports status UNVERIFIED unless its promotion contract passes. |
| DWCS | `config/dwcs_s10w3_2026-08-25.json` — a recovery-only card definition for Season 10 Week 3 (Aug 25, 2026), matchups "verified from current UFC.com DWCS Week 3 previews," with a ±1-day freshness guard so it cannot silently become a stale card; DWCS handling inside `build_ufc_live_inputs.py` (an explicit date-bounded DWCS card wins over UFCStats' next ordinary UFC event) | `config/ufc_market_surface.json` governance: **`dwcs_requires_event_specific_validation: true`**. The UFC training artifact records `dwcs_specific_validation: UNVERIFIED` — "Current UFCStats event history does not provide a historical DWCS training/holdout slice; UFC-debut validation is not treated as DWCS validation." |

DataGolf appears in the repo only as an X/social source handle
(`sportsedge/social_analytics_sources.py`: "@DataGolf — golf_projections_course_fit_and_live_modeling").
**There is no DataGolf data admission, no Kaggle admission, and no odds-archive admission for any
of the three sports.**

---

## 1. PGA — verdict: DATA-RICH, with one paid keystone

### 1.1 DraftKings market surface (verified this session from DK market listings/reviews)

Per PGA Tour event: outright winner, top-5 / top-10 / top-20 finish, tournament head-to-head
matchups, 3-balls, first-round leader, round leaders and round matchups, make-cut props,
hole-by-hole live betting; majors carry expanded menus (lowest round, nationality props,
specials). Coverage extends beyond the PGA Tour (DP World Tour, LIV, LPGA) but the PGA Tour +
majors menu is by far the deepest. This surface maps cleanly onto the repo's existing market
families (OUTRIGHT, FIRST_ROUND_LEADER, TOP_K, MAKE_CUT, H2H); DK does not post the repo's
unsupported shapes (round-score/birdie/bogey/hole props, group winner) as standard pre-tournament
families either, so engine and book agree on scope.

### 1.2 Source matrix

| Source | Access | What it gives | Evidence state / notes |
|---|---|---|---|
| **DataGolf API** (feeds.datagolf.com) | **Paid — Scratch Plus only.** Monthly Plus $30/mo (API, *no archive endpoints*); **annual Plus $270/yr adds the archives** (raw scores/SG/stats, predictions archive, betting-odds archive, DFS points archive). Scratch Basic $20/mo / $190/yr has predictions, odds screens, custom SG queries, DFS projections — but **no API** | Six endpoint families (verified on datagolf.com/api-access): General Use (player list + DataGolf IDs, tour schedules, field updates, tee times, DK/FanDuel DFS salaries); Model Predictions (pre-tournament + live + historical archive: win/top-5/10/20/make-cut probabilities, baseline and baseline+course-fit variants); Historical raw data (round-level scores, SG splits, stats back to ~2017 PGA / earlier in archives); Betting odds archive (outrights, matchup/3-ball odds history); DFS points/salaries archive. 45 requests/min, key-in-query auth | Pricing and tier contents verified on datagolf.com/subscribe this session; endpoint families, rate limit, and "API requires Scratch Plus" verified on datagolf.com/api-access this session. A community Python wrapper (`data_golf` on PyPI) documents the same endpoints. **This is the single source that supplies skill estimates (DG Index / true SG by category), course-fit inputs, fields, AND a market-baseline odds archive in one contract.** |
| **DataGolf free web surfaces** | Free | DG Rankings / Data Golf Points pages (public top-500 tables), player profile pages (career summary, ranking evolution), true-SG pages | Partial by design: the Skill Ratings page states the full table (451 players this week) requires a Scratch membership; the Predictions Archive page is subscriber-gated ("gives subscribers the ability to download…"). Free surfaces suffice for spot checks and identity crosswalks (DG player IDs), **not** for a systematic feed. |
| **OWGR** (owgr.com) | Free | Official weekly world rankings (full list, updated Mondays); historical Top-300 ranking PDFs back to 1986 | Verified on owgr.com this session (archive page + current list live, week of Oct 26, 2026). Useful as a public, point-in-time-safe prior and as the identity/ranking cross-check. OWGR is a *results* ranking, not a strokes-gained skill estimate — a prior, never the model. |
| **PGA Tour stats** (pgatour.com/stats) | Free (public HTML) | Season-level strokes-gained categories (OTT, APP, ARG, PUTT, T2G, Total), scoring, driving, putting aggregates per player per season | Site reachable (HTTP 200) this session; stat pages are the long-standing public `.html` stat tables the community scrapes. Season aggregates only — **no public round-level ShotLink**; adequate for priors/feature cross-checks, not a primary feed. |
| **Kaggle golf datasets** | Free account | `robikscube/pga-tour-golf-data-20152022` — round-level results with SG splits, 2015–2022; `jmpark746/pgatourdata-2010-2018` — season aggregate stats 2010–2018 | Contents verified via multiple independent downstream users this session (not re-downloaded; Kaggle requires an account this task does not create). **Design data only** — both are stale (end 2018 / 2022), neither carries book odds. Useful for construction design and feature sanity checks; neither can validate. |
| **PGASharp** and similar DataGolf-powered tools | Free beta (third party) | Form ratings, course history, DK salaries, live leaderboard | Noted for completeness: a convenience layer *on top of* DataGolf, not a source of record. Do not build on it. |
| Sportradar / IMG Arena live scoring; SportsDataIO golf | Paid, enterprise/commercial license | Official live hole-by-hole scoring feeds | Owner-decision list only; not needed for a pre-tournament construction. Live in-play is a later problem (see §1.4). |

### 1.3 What a first construction is built on

The engine already exists — the first construction is an **input-acquisition + validation**
construction, not a new model:

1. **Skill layer:** DataGolf DG Index / true-SG category estimates per player, snapshotted
   pre-tournament (point-in-time, hash-stamped) → the snapshot format `sportsedge/pga/`
   already consumes.
2. **Priors/cross-checks (free):** OWGR weekly rank; PGA Tour season SG aggregates;
   course-history finishes assembled from DataGolf's historical raw archive.
3. **Market baseline:** DK closing prices captured by the lines lane, de-vigged exactly per the
   frozen `config/pga_benchmark_methodology.json` (full-field multiplicative for OUTRIGHT/FRL;
   binary paired for TOP_K/MAKE_CUT; paired two-way for H2H). DataGolf's betting-odds archive
   is a *secondary* baseline source — book identity per row must be verified before any use as
   a baseline, and untimestamped rows inherit the standing "never verified CLV" label.
4. **Natural first validation targets:** H2H and TOP_K — binary, paired prices, no full-field
   completeness requirement — before OUTRIGHT (which needs the complete field at close).

### 1.4 Capture implications

- Tournaments run **Thu–Sun**; fields finalize the prior week, DK outrights typically post
  Mon–Tue. Fits the standing two-write cadence: one capture ~T-1H before the first tee time
  Thursday (pre-tournament close for outright/top-K/H2H), plus a pre-cut capture Friday evening
  if live families are ever priced. In-tournament live capture is a *new* scope and is **not**
  required for the first construction.
- Dead-heat and cut semantics are settlement-critical and already encoded in the frozen
  methodology; captures must record the full field (a partial outright field can never be
  de-vigged — fail-closed, per the status doc).

---

## 2. UFC — verdict: WORKABLE on free sources; the odds-archive join is the gap

### 2.1 DraftKings market surface (verified this session)

Moneyline; total rounds (0.5–4.5 lines); fight to go the distance (yes/no); method of victory
(fighter × KO/TKO/DQ, submission, decision — plus exact-method variants); winning round / round
betting; points spread; same-game parlay across fight markets; live in-play. The repo's engine
supports only MONEYLINE_H2H today, so DK's prop menu is *ahead of* the engine — method/round/
distance families each need their own engine extension + validation contract before they can be
priced, exactly as `config/ufc_market_surface.json` already states.

### 2.2 Source matrix

| Source | Access | What it gives | Evidence state / notes |
|---|---|---|---|
| **ufcstats.com** (official UFC stats) | Free web | Complete event/fight/fighter statistics: round-by-round significant strikes by target, takedowns, control time, knockdowns, submission attempts; fighter profiles (height, weight, reach, stance, DOB); full event history back to 1993, including DWCS events as ordinary listed events | **Verified caveat this session: plain HTTP clients from this runtime receive a JavaScript bot-check interstitial (both attempts returned the ~3 KB challenge page, zero event data).** The repo's own `sportsedge/ufc_source.py` fetches ufcstats.com directly via urllib and is therefore exposed to the same gate. Treat direct ufcstats pulls as *unreliable until re-proven*; the mirror route below is the robust path. |
| **Greco1899/scrape_ufc_stats** (GitHub) | Free | Maintained full scrape of UFCStats as CSVs in-repo (fighters, events, fight results + per-fight stats) | **Already the repo's pinned training source** — `scripts/build_ufc_training_artifact.py` stamps `training_source: "Greco1899/scrape_ufc_stats UFCStats mirror"` and `.github/workflows/ufc-full-model.yml` asserts that exact string. Admission-grade status: it is *used*, with a freshness contract (`training_data_max_age_days`); this scoping does not change that. Freshness must be re-verified at each pull (community-maintained). |
| **Hugging Face: xtinkarpiu/ufc-fight-data** | Free | Full UFCStats scrape transformed to one row per fight (both fighters' columns) with pre-fight cumulative metrics computed | Dataset card states data extracted **Mar 10, 2025** — a stale snapshot. Design/cross-check use only; the Greco1899 mirror supersedes it for freshness. |
| **Kaggle UFC datasets** | Free account | `rajeevw/ufcdata` (the canonical older UFCStats scrape incl. raw_total_fight_data); `mdabbert/ultimate-ufc-dataset` (fight stats + rankings + betting-line columns, used by published modeling work); `neelagiriaditya` UFC DATASETS 1994–2025 (fighter_details with win-method breakdowns); `azhou19` ESPN-sourced fight data incl. odds | Contents verified via dataset descriptions and independent downstream users this session (not re-downloaded). All are *snapshots of* UFCStats/ESPN — provenance is the upstream site, staleness varies by dataset. Design data; the live feed remains the mirror. |
| **BestFightOdds** (via `ufcscraper`, PyPI: balaustrada/ufcscraper) | Free web | Historical UFC **closing odds** by fight — the standard free closing-line archive for MMA; the scraper joins BFO odds to UFCStats fights | Directly answers the repo's own recorded gap: the training artifact states "Fresh UFCStats fight history contains no sportsbook prices. A separately joined, fight-matched closing-odds archive is required." BFO is consensus/archive odds, **not DraftKings-specific** — it can serve as the contemporaneous market baseline for design screens with the label stated; DK forward captures remain the counting baseline. Join quality (fighter-name matching) must be audited before any screen trusts it. |
| **ESPN MMA API** (site.api.espn.com …/sports/mma/ufc) | Free (undocumented public JSON) | Scoreboard/events, fighters, results for the UFC league | **Verified by sample pull this session** (scoreboard endpoint returned the live UFC league object, id 3321, 2026 season). Useful for schedules/results cross-checks and card assembly; stats depth is far below UFCStats; odds surfaces are partial. Never a primary stats source. |
| **Tapology** | Free web | Fighter profiles with **full professional records including regional bouts**, bout pages, event pages, rankings | Reachable from this runtime this session (HTTP 200, full HTML with a browser user-agent). No official API; heavy pages; terms-of-use care and rate discipline required. Its unique value is *pre-UFC* records — see DWCS. |
| **Sherdog** | Free web | Fight Finder records database; complete DWCS event history (89 events, ~440 matches to date per its org page) | Reachable from this runtime this session (HTTP 200). Same no-API, handle-with-care status as Tapology; strongest for historical event/record verification. |

### 2.3 What a first construction is built on

The construction is already designed (`docs/ufc_model_design.md`): pre-fight UFCStats snapshots
(strictly before bout time) → age/reach/stance + rolling striking/grappling rates + opponent-
adjusted strength + Elo → calibrated logistic baseline, GBM challenger, ensemble only after
walk-forward validation vs the closing no-vig baseline. What scoping adds:

1. **Feed:** Greco1899 mirror as primary (already pinned), ufcstats direct as cross-check only
   while the bot gate stands.
2. **Baseline join (the missing piece):** BestFightOdds closing odds joined fight-by-fight,
   audited for match rate and name collisions, labeled as archive-consensus baseline.
3. **First family:** MONEYLINE_H2H (the only supported market). Method/round/distance require
   the joint-outcome layer the design doc already specifies (250k-draw Monte Carlo over
   calibrated joint outcome probabilities) plus their own holdout contracts — later work,
   explicitly not implied by an ML pass.

### 2.
...[truncated 5873 chars]