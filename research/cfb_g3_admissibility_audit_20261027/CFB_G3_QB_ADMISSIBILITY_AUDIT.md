# CFB GAP-G3 ADMISSIBILITY AUDIT — point-in-time starting-QB designations

**Audit date:** October 28, 2026 (overnight Oct 27–28, America/Chicago)
**Charge:** `VERIFIED_MODELS_GAP_FILL_PLAN_20261027.md` §2 (Gap G3), §3.2 (proxy stack),
build-order item 4, plus the owner's expansion of the same night adding one more
source class — school-published weekly game-notes / depth-chart PDFs.
**Auditor:** Rocky (Muse), independent audit pass. No construction was designed in
this task, per the brief. Nothing in this report resurrects any retired construction.

## VERDICT — EXIT (b): NOT ADMISSIBLE

**No freely available source provides point-in-time, pre-kickoff CFB starting-QB
designations for design seasons, and no proxy's leak can be bounded tightly enough
to substitute for one.** Per the plan's standing verdict and build-order item 4:

> **CFB sides and CFB totals are recorded NO VIABLE CONSTRUCTION on available
> inputs.** The four retired constructions (PM, AM, PRIOR_CURRENT_BLEND,
> CFB_CONVERGED_ANCHOR_V1) stay retired. CFB effort redirects to **team totals
> design** (data-sufficient: CFBD closes + play-by-play) and **forward prop
> capture**, per the plan.

The audit found one genuinely point-in-time artifact class (school game-notes
PDFs, §5.5) and one recorded-starter field that turns out to be a mirage for the
design seasons (§5.3). Neither cures G3. The detailed evidence follows; the single
most decisive facts are:

1. The only recorded-starter field in the public CFB data universe —
   `starter` in SportsDataverse's `espn_cfb_game_rosters` — is populated for
   **0.0% of team-games in 2023 and 0.0% in 2024**, and covers only **41.9%** of
   team-games in 2025 (measured, §5.3). There is no nflverse-equivalent
   recorded-QB field for CFB design seasons.
2. The best post-hoc proxy (play-by-play first passer) recovers the recorded
   starter 97.0% of the time where a record exists — but a *designation* is not
   an identity. The gap between the announced/expected starter and the actual
   starter is **structurally unobservable in every free source**, and it sits
   inside a 15–19% week-to-week starter-churn class that cannot be excluded
   without biasing any screen (§6).

## 1. The gating question and the standard applied

G3 asks for: *who was the announced/expected starter before kickoff, timestamped*,
for design seasons — the input whose absence forced the converged-anchor screen
(PR #2789) to record its backup-QB feature as NOT EVALUATED ("Historical
point-in-time backup-QB change receipts were unavailable"), and whose absence is
the stated conditional on the standing verdict that score-only CFB constructions
are not viable.

A source is ADMISSIBLE for G3 only if it is (a) genuinely point-in-time (the
designation as it stood before kickoff, not reconstructed afterward),
(b) complete enough to compute the feature across a design window (full-slate,
or missingness that is itself modelable), and (c) reproducible — pinned or
pin-able with provenance, per the program's source-admission discipline.
A proxy is admissible only if its total leak against the true designation can be
**bounded** and the bound can be enforced by a stated sensitivity-exclusion rule
(the standard the plan itself applied when admitting nflverse's recorded NFL
starting QBs as a DESIGN feature in §3.1).

## 2. What was measured, and on what universe

All quantitative claims below were measured in this audit from files pulled on
2026-10-28 from `sportsdataverse/sportsdataverse-data` GitHub releases:

| Dataset (release tag) | Files pulled | Size |
|---|---|---|
| `espn_cfb_pbp` | `play_by_play_2023.parquet`, `_2024`, `_2025` | 50.7 / 55.0 / 59.5 MB |
| `espn_cfb_player_box` | `player_box_2023.parquet`, `_2024`, `_2025` | 0.66 / 0.83 / 0.84 MB |
| `espn_cfb_game_rosters` | `game_rosters_2023.parquet`, `_2024`, `_2025` | 11.6 / 12.3 / 11.6 MB |

Universe: every team-game in `espn_cfb_player_box` where the team recorded ≥1
pass attempt — 1,822 (2023), 1,930 (2024), 1,914 (2025) team-games. This is
ESPN's Division-I coverage as carried (FBS + FCS opponents included), **not** the
#2789 screen's Week-5+ FBS/FBS cohort; the limitation is stated plainly because
the rates below are population rates. It does not affect the verdict: the two
decisive findings (an empty starter field in 2023–24; no designation archive
anywhere) are universe-independent, and QB-usage leak mechanics (early exits,
rotations, trick plays) are not materially different by subdivision.

Measurement script and raw output are committed beside this report
(`measure_leak.py`, `leak_measurements.json`) so every number reproduces.
Definitions: *primary passer* = the team's passer with the most attempts in the
game (game-log identity); *first passer* = passer on the team's first
pass-attempt play in play-by-play order; *flagged starter* = athlete with
`starter = True` in `espn_cfb_game_rosters` who threw ≥1 pass for that team-game
(identification rule disclosed: a flagged non-QB who threw one trick pass counts
as a flagged passer, which inflates the multi-flag rate in §5.3 — the bias is
against the source, and the coverage rates are unaffected).

## 3. Measured leak table (all rates % of team-games)

| Metric | 2023 | 2024 | 2025 |
|---|---:|---:|---:|
| First passer present in PBP | 99.12 | 98.03 | 99.79 |
| First passer ≠ primary passer | 7.75 | 5.66 | 5.55 |
| First passer attempted <5 passes | 3.27 | 2.22 | 2.09 |
| First passer attempted <10 passes | 6.31 | 5.50 | 5.18 |
| Primary passer attempted <20 passes (rotation/no-full-game QB) | 19.10 | 18.50 | 18.03 |
| Sensitivity-exclusion union (proxy stack) | 9.88 | 8.81 | 7.37 |
| Primary passer changed vs team's previous game (churn) | 19.27 | 16.00 | 15.02 |
| **Recorded-starter (`starter` flag) QB coverage** | **0.00** | **0.00** | **41.85** |

2025 flagged subset (n ≈ 801 covered team-games): flagged starter ≠ primary
passer 6.99%; flagged starter attempted <10 passes 7.24% (<5: 3.87%); ≥2 flagged
passing "starters" 7.12%; flagged starter changed vs previous game 15.86%;
exclusion union on the flagged stack 8.74%. Where both exist, **first passer =
flagged starter in 97.00%** of team-games (flag ≠ first passer 3.00%).

## 4. Reading of the numbers

The observable leak is real but not the problem. Roughly 5–8% of team-games have
a first passer who is not the team's primary passer (trick plays, early exits,
packages), 5–6% have a first passer who attempted fewer than 10 passes, and a
sensitivity rule excluding the union discards 7–10% of team-games. In ~18–19% of
team-games no passer attempts 20 passes at all — QB rotation is a structural
feature of college football, not noise. And in 15–19% of team-games the primary
passer differs from the previous game's — the churn class inside which any
designation error must hide.

## 5. Source-by-source findings

### 5.1 (i) CFBD player game stats + cfbfastR/SDV play-by-play first-passer identity

**Finding: post-hoc identity only; designation leak unboundable. NOT ADMISSIBLE
for G3.** CFBD was not queried with any key in this audit (per brief); its
player-stats contents are as verified in the plan §3.2 — who played, never who
was designated. The PBP leg was measured directly (§3): first-passer identity is
recoverable for ~98–99.8% of team-games and agrees with the recorded starter
97.0% of the time where a 2025 record exists. That validates first-passer as an
*identity inference*. It cannot validate it as a *designation*: the inference is
derived from the game itself, so by construction it can never disagree with what
happened — only with what was announced, and no free source records the
announcement to check against (§6).

### 5.2 (ii) ESPN depth charts via the cfbfastR ESPN family

**Finding: current-state only; no archived point-in-time snapshots exist in
this universe. NOT ADMISSIBLE.** Verified in this audit: (a) no cfbfastR loader
whose name references depth charts exists in the package's R sources; (b) the
SportsDataverse data repo's only injury-adjacent CFB release, `espn_cfb_injuries`,
is a single current-state snapshot (`injuries_2026.parquet` + timestamp files,
updated 2026-10-27) — it is not an archive and contains no design seasons;
(c) ESPN's published depth charts are live web state, overwritten in place.
Corroborating scarcity: SportsDataIO's own NCAA workflow documentation states it
"does not provide depth chart or lineup information for college sports" at all
(commercial vendor, checked for market color only — paid sources are out of
scope under the program's free-only law regardless).

### 5.3 (iii) A recorded-starter field — the nflverse-equivalent hunt

**Finding: the field exists in schema and is empty where it matters. NOT
ADMISSIBLE for design seasons.** The full SportsDataverse release inventory was
enumerated in this audit (383 releases; every CFB-family tag — 100+ datasets:
PBP, player/team box, schedules, drives, game rosters, participants, betting,
FPI, recruiting, portal, usage…). **No depth-chart dataset and no starter
dataset exists.** The single starter-bearing candidate is the `starter` column
inside `espn_cfb_game_rosters`. Measured population of that column:

- 2023: 0 of 216,281 roster rows flagged (`starter = True` count: **0**)
- 2024: 0 of 231,077 rows flagged (**0**)
- 2025: 17,616 flagged rows → a passing starter identifiable for only
  **41.85%** of team-games, with 7.12% of covered team-games flagging ≥2
  passers and 6.99% of flagged starters not being the primary passer.

So even the recorded-identity leg — the weakest form of the input, and the one
the NFL precedent admitted — **does not exist for the 2023–2024 design seasons
and is a 42% patchwork in 2025**, with an unknown selection mechanism (the flag
appears with a newer processing pipeline; which games got flagged is not
documented, so the missingness cannot be modeled). The classic cfbfastR PBP
(`cfbfastR_cfb_pbp`, 2014+) carries no starter field at all.

Note the contrast that decides the precedent question: nflverse's recorded NFL
QB was admitted because the field is *complete across all design seasons* and
the NFL's official inactive-report system bounds the scratch class from outside
the dataset. Neither condition holds here.

### 5.4 (iv) Other public repositories and archives

**Finding: nothing carries timestamped CFB starter designations. NOT
ADMISSIBLE.** Checked in this audit:

- **College Football at Sports-Reference.com** — no depth-chart product or
  archive exists on the CFB site (search-verified; the site carries results,
  box scores and player news archives, no depth charts of any vintage).
- **GitHub** — repository search for CFB depth charts returns current-state
  tooling only (e.g. a depth-chart *builder* that imports live rosters; a
  current-season depth-chart/ratings app). No repository archives historical
  weekly depth charts or starter announcements as data.
- **GunslingerBuzz QB-room tracker** (surfaced via Sports-Reference news
  archives) — weekly *journalism* about QB rooms across 2023–2024, not a
  dataset: no machine-readable designations, no completeness claim, no data
  license. Beat reporting, i.e. plan §3.2 proxy (iii), which the plan already
  classed as "not a dataset."
- **Conference availability reports** (Big Ten from 2023, SEC from 2024; other
  conferences per vendor documentation) — genuinely timestamped, pregame, and
  official, but they report *availability* (probable/questionable/out), not
  starter designations; they cover a minority of FBS conferences; and they live
  as web postings/PDFs with no dataset archive. They cannot designate a starter
  and cannot cover a design window. Noted so the record shows they were
  considered and why they fail.

### 5.5 (v) School-published weekly game notes / depth-chart PDFs (owner-added class)

**Finding: the only genuinely point-in-time designation artifacts found — and
they fail as a dataset on coverage verifiability, designation ambiguity, and
extraction cost. NOT ADMISSIBLE as a dataset; admissible only as spot-check
color.** This class is real, and the audit verified dated exemplars directly:

- **Boise State** (broncosports.com): game-notes PDFs at dated document paths —
  `/documents/download/2024/9/3/…` (for the Sep 7, 2024 game),
  `/documents/download/2024/11/27/2024-11-29_Boise_State_Football_Notebook.pdf`,
  `/documents/download/2025/8/23/2025-08-28_Boise_State_Football_Game_Notes.pdf`
  — with a printed two-deep depth chart (the Nov 2024 notebook carries the full
  chart on p. 23). Upload-dated *before* kickoff: genuinely point-in-time.
- **Mercer notes hosted on Alabama's site** (rolltide.com):
  `/documents/download/2024/11/12/Mercer_Notes.pdf`, published Nov 12, 2024 for
  the Nov 16 game at Alabama, containing Mercer's two-deep including the QB
  line. Opened and read in this audit.
- Older persistence confirmed: Purdue's 2022 Week 1 notes PDF (hosted via Penn
  State's Sidearm S3) and UT Martin's 2017 weekly notes with a date-stamped
  filename (`2017_FLCFB_WeeklyNotes_092717.pdf`) on Sidearm S3 — the artifact
  class spans platforms (Sidearm, PrestoSports/S3) and years.

Why it still fails, quantified honestly:

- **Coverage is unverifiable, therefore not boundable.** There is no index,
  registry, or archive of these documents for any season — not in
  SportsDataverse, not on GitHub, not at the conferences. Completeness must be
  established school by school across **134 FBS programs (2024; 136 in 2025)**
  on heterogeneous platforms whose document URLs rot and reorganize. In this
  audit's targeted sample, dated notes PDFs were directly retrievable for 2 of
  3 programs attempted (Alabama, Boise State); an Ohio State notes PDF did not
  surface as a document in search at all (media coverage of the chart did).
  A patchwork in the 40–70% range — the plausible outcome of a heroic scrape —
  is, in the owner's own framing for this audit, *a finding, not a cure*: the
  missingness concentrates in smaller programs and specific weeks, and no
  completeness oracle exists to measure what was missed.
- **The designation itself is often deliberately ambiguous.** Two-deeps
  routinely list co-starters with "OR" (Alabama's 2024 Week 1 chart listed
  "or" at multiple positions, per contemporaneous reporting), some programs
  omit the chart in some weeks or have stopped publishing one at all, and the
  chart is published Tue–Fri — a Tuesday designation cannot see a Saturday
  scratch, so a residual leak survives even perfect extraction.
- **Extraction cost is prohibitive relative to verifiability.** Full FBS
  coverage for 2023–2025 means ≈ 134 schools × ~13 weeks × 3 seasons ≈ **5,200
  PDFs**, each with school-specific, season-drifting layouts. Both documents
  converted in this audit show the multi-column two-deep interleaving under
  text extraction (offense/defense columns scrambled), so reliable QB1
  extraction requires layout-aware per-school parsing plus manual QA — a
  multi-week build whose recall can never be audited. The program's admission
  standard (provenance + reproducibility + completeness must check out) cannot
  be met by construction.

## 6. Why the leak cannot be bounded — the core argument

Strip away every fixable problem and one irreducible gap remains, and it is the
gap G3 actually names. Every candidate source records — at best — **who
actually started**. G3 requires **who was designated before kickoff**. The
difference between the two is the late-scratch / game-time-decision class:
announced starter held out, concealed QB change, Saturday-morning decision.
College football has no standardized designation system for most conferences in
the design seasons (no official inactive lists; availability reports cover a
minority of conferences and only recent seasons), coaches are incentivized to
conceal exactly this information, and **no free source archives the announcement
side of the comparison** — so the class's size cannot be measured from data,
only asserted.

What can be measured shows the class has room to be material: the starter
changes week to week in **15–19% of team-games** (§3). Announced midweek
changes (admissible, knowable) and unannounced late changes (leak) are
indistinguishable inside that class from post-hoc data. The two candidate
treatments both fail:

- **Exclude all starter-change team-games** → discards 15–19% of the sample,
  non-randomly: changes concentrate around injuries, benchings and blowouts —
  the highest-information games for a QB-sensitive construction — biasing any
  screen that results.
- **Retain them** → embeds an unknown mislabel rate in exactly the feature the
  construction exists to exploit, concentrated in the games where the QB term
  moves the price most. A screen run on such a feature can pass or fail for
  reasons invisible to the auditor — the definition of an inadmissible input
  under the plan's own standard.

The nflverse NFL precedent does not rescue the proxy: there, the recorded field
is complete in every design season, official inactives bound the scratch class
externally, and the plan admitted the field as a *design feature with a named
residual class + mandatory sensitivity exclusion* — not as a designation.
Here the field is empty/partial (§5.3) and no external bound exists.

## 7. Verdict and its exact consequences

**EXIT (b) — NOT ADMISSIBLE**, for every source class audited, including the
owner-added game-notes class. Therefore, per the plan:

1. **CFB sides and CFB totals are recorded NO VIABLE CONSTRUCTION on available
   inputs — permanently, on available inputs.** The gating conditional on the
   standing verdict ("unless admissible point-in-time QB inputs appear") is
   resolved: they do not exist in the free public record for design seasons.
2. The four FAILED constructions (PM, AM, PRIOR_CURRENT_BLEND,
   CFB_CONVERGED_ANCHOR_V1) **stay retired**. This audit evaluates inputs, not
   constructions; nothing here reopens any of them.
3. **Redirect (already the plan's exit-b path):** CFB effort moves to
   **team totals design** — data-sufficient on CFBD closes + play-by-play — and
   to **forward prop capture** (G1: no historical prop lines exist; forward DK
   capture is the only path).
4. One precision for the redirect, so this verdict is not over-read: identity
   and usage from **past games** (strictly before the priced game) are post-hoc
   facts that are fully knowable at pricing time and are **clean under
   walk-forward discipline** — the first-passer/primary-passer stack measured
   here (98–99.8% recoverable; ~97% agreement with the recorded starter where a
   record exists) may be used freely for features about *prior* games (e.g.
   QB-usage shares in a team-totals design). G3 blocks only features that
   require the **current game's** pre-kickoff designation. A future construction
   that uses no current-game designation does not need G3 cured — designing one
   is a separate task, outside this audit.
5. Re-audit triggers, stated narrowly so "permanently" stays honest: this
   verdict is about *available inputs*. It reopens only if (a) a timestamped
   designation record with verifiable full-slate coverage for design seasons
   surfaces, or (b) the `espn_cfb_game_rosters` starter field is backfilled to
   complete coverage for full design seasons — which would still admit only a
   recorded-starter feature under the NFL-style named-leak discipline, not a
   designation.

## 8. Companion item — CFBD betting-lines DESIGN-baseline admission verdict

Build-order item 4 pairs this audit with the formal admission of the CFBD lines.
Recorded here as the formal verdict:

> **CFBD betting lines (2013–present): ADMITTED as a DESIGN baseline.**
> Contents as verified in the plan §3.2 against the `cfbd_betting_lines`
> documentation: opening **and** closing spread, opening **and** closing total,
> home/away moneylines, by provider (Caesars / consensus / numberFire /
> teamRankings). Open/close snapshots carry **no quote timestamps** → design
> baseline only, under the standing labels: flat −110 ROI is an ASSUMPTION and
> is always labeled; comparisons against these closes are **never verified
> CLV**. This is seen data — the failed CFB constructions already faced it —
> and its admission changes no construction's status. Hash-pinning of the pull
> is handled by a separate workflow item (documented-only in PR #2831 at audit
> time; the pin was not fetched with any key in this audit).

## 9. Evidence states

- **Independently verified / measured in this audit:** all rates in §3;
  starter-column population counts 2023–2025; the SportsDataverse release
  inventory (383 releases, CFB tag enumeration); absence of a cfbfastR
  depth-chart loader; the `espn_cfb_injuries` single-snapshot state; the Boise
  State dated-notes exemplars and the Mercer two-deep document (opened and
  read); Sports-Reference CFB's lack of a depth-chart product (search-level);
  SportsDataIO's no-CFB-depth-charts statement (their published docs).
- **Documented-only (carried from the plan's Oct 27 verification, not re-pulled
  here):** CFBD betting-lines contents (§8); CFBD player-stats contents (§5.1).
- **Not verified:** a complete per-school game-notes archive for any single
  program across 2023–2025 (no such archive was located to verify); Ohio State
  notes PDFs (not surfaced as documents in search); GunslingerBuzz's coverage
  completeness (blog; not treated as a source).
