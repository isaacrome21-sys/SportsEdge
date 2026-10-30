# GAP SOURCE HUNT — G1 / G2 / G4 / G5 (Phase 2)

> **SUPERSEDING SOURCE-INTEGRITY HOLD — 2026-10-28 (G1 SMARTSTAKE ONLY).**
> The G1 verdict `FOUND-ADMISSIBLE candidate` and §3.1 claims below are a
> historical discovery report, **NOT a current admission or safe modeling input**.
> Independent audit of canonical SmartStake revision
> `049dd4caeb562010a5806207c413e9f9bc012825` found **18** Parquet files,
> not the 20 claimed here. Three of four recorded sample hashes conflict with
> upstream Git-LFS OIDs: May part-002 is the empty-byte SHA-256 despite a
> 46,574,006-byte upstream object; June part-000 and part-003 also differ.
> The README's `ts/start_time` schema is not reconciled with the reported
> `snap_ts/tick_ts/start_ts/close_ts/is_close/outcome_known/segment` columns.
> The upstream OIDs are publisher assertions, not independently downloaded and
> rehashed full-file evidence. **G1 status: SOURCE_PIN_CONFLICT / NO ADMISSION**.
> No historical SmartStake screen, training, comparison-to-close or validation
> may rely on these claims until exact-revision complete-byte pins, Parquet
> footer/schema, bookmaker/game identity, PIT chronology, and preregistered
> split are independently verified. Preserve the original report below as
> historical evidence; see PR #2865 for the separate PINS.md correction.


Executed Oct 27–28, 2026 (America/Chicago), under the owner's directive: anything we are
missing, check **all** available sources including GitHub repos. Companion to
`VERIFIED_MODELS_GAP_FILL_PLAN_20261027.md` (§2 gaps, §3 Phase-1 verdicts). G3 was excluded
(sibling audit). G6/G7 were not targets. This hunt re-verified every candidate against the
actual repo/dataset page **or a sample pull** — README claims alone were never admitted.

**Owner law applied:** FREE-ONLY data is absolute (Isaac, Oct 27, 2026 ~23:20 CT —
"I ain't paying not"). Every paid source is recorded once, in §7, as CLOSED by that ruling.
Admission bar (unchanged): point-in-time safe, no lookahead, reproducible/pinnable;
untimestamped closes are never "verified CLV"; flat −110 ROI is a labeled assumption.

**Search surface (for every NOT FOUND below):** GitHub repository search + code search
(query families: nba/nfl/mlb/ncaab + odds/betting/props/closing/pinnacle/betfair/draftkings,
plus filename search for `nba_2008-2026.csv` and content search for its `whos_favored`
column); Hugging Face dataset API (searches: nba odds, nba betting, sports betting odds,
sportsbook odds, player props, draftkings, nba, betting, odds); Kaggle catalog via web
search and cross-references from GitHub (one direct Kaggle dataset-page open failed with a
tool error — Kaggle coverage therefore rests on web-search results plus the in-repo
DATASET_REGISTRY, and is labeled accordingly); archive.org / Wayback CDX for the classic
SBR archives; aussportsbetting.com; the datafield.dev and sportsapis.dev source
directories; vendor documentation pages (The Odds API via published comparisons quoting
its v4 guide, EndzoneAPI, PropLine, ParlayAPI, TheOddsGap).

---

## 0. Verdict summary

| Gap | Verdict | One-line basis |
|---|---|---|
| **G2** per-book NBA closes 2023+ w/ timestamps | **NOT FOUND (free)** | Every free candidate is date-only consensus/median or single-line SBR. Timestamped per-book snapshots exist only behind The Odds API's paid historical endpoint (§2.3). Access to the *design* file is cured by a verified GitHub mirror (§2.2), but the file itself does not cure G2. |
| **G1** historical prop closes w/ timestamps | **FOUND-ADMISSIBLE candidate — MLB only** | SmartStake HF dataset: minute-level per-book MLB prop quotes incl. DraftKings, graded, CC BY 4.0 (§3.1, admission draft attached). NFL: free-tier commercial surface only (§3.2). NBA/CFB/CBB: NOT FOUND. |
| **G4** timestamped MLB game-line archive | **NOT FOUND (free)** | Free candidates are date-only (SBR family incl. a verified 2011–2021 scrape; a 2025 consensus file). No free per-quote-timestamp MLB archive exists on the searched surface. |
| **G5** full-slate historical CBB closes | **AUDIT COMPLETE → design-baseline admissible** | SBR NCAAB Excel archive (2007-08→2021-22) pulled and audited: coverage, missingness, and score/close spot-checks pass (§5). Validation leg stays NO_DATA (date-only, no per-book identity) — unchanged from Phase 1. |

---

## 1. What "admissible" would have required

For G2/G4 the bar is a **timestamp-authenticated** baseline: per-book lines with quote
timestamps, so a screen can prove the price existed before tip. Date-only closes can
anchor *design* screens (with the standing labels) but can never validate. For G1 the bar
is per-book prop lines with timestamps (an open/close pair per book is the minimum viable
form; tick/minute history is stronger). For G5 the open question was narrower — whether
the SBR NCAAB archive is good enough to serve as the CBB **design** baseline — and that is
the question the audit in §5 answers.

---

## 2. G2 — Per-book NBA closing lines 2023+ with quote timestamps

### 2.1 NOT FOUND on the free surface

Every free candidate located is date-only and/or consensus:

- **Kaggle cviaxmiwnptr/nba-betting-data** — SBR consensus → ESPN → SBR median segments;
  date-only, not per-book (Phase 1, §3.3; not re-litigated).
- **Hugging Face `minmaxxxer/nba-odds-2026-27`** — consensus opening/closing lines, one
  row per game, 2026-27 season to date (43 games at pull time), weekly updates, CC BY 4.0.
  Date-only, no book identity. Design-grade at best; DK forward capture is strictly
  better for the current season.
- **flancast90/sportsbookreview-scraper NBA archive** (GitHub, MIT) — SBR family,
  2011–2021 pre-scraped JSON; date-only (see §5.3 for the verified MLB leg schema).
- **aussportsbetting.com NBA dataset** — free Excel; opening/closing lines incl. Pinnacle
  head-to-head; **date-only**. Design-grade.
- **Direct SBR NBA archive** — verified in §5.2: seasonal Excel 2007-08→2022-23, date-only,
  no per-book identity. It is the cleanest form of the design data, and it still is not G2.

### 2.2 MIRROR of the Kaggle NBA file — FOUND and pinned (access route, not a G2 cure)

The repo's own Kaggle pull is blocked behind a GitHub-Actions `workflow` scope wall.
A byte-size-exact mirror of the same file exists on GitHub:

- **Location:** `andrewgkim-neu/nba-playoff-predictor`, path `data/kaggle/nba_2008-2026.csv`
  (committed 2026-07-06, "Initial commit").
- **Size:** 2,493,308 bytes — exactly Kaggle's stated 2.49 MB for `nba_2008-2026.csv`.
- **sha256:** `729eb2ead85c14affbb81ae9a4c611fee9790b8dd3d1d7824e1ddba14410a8c4`
- **Measured contents:** 24,440 rows × 27 columns; schema identical to the Kaggle file
  (`season, date, regular, playoffs, away, home, score_away, score_home, q1..q4, ot,
  whos_favored, spread, total, moneyline_away, moneyline_home, h2_spread, h2_total,
  id_spread, id_total`); dates 2007-10-30 → 2026-06-13 (Kaggle page: Oct 2007–Jun 2026).
- **Identity evidence — strong but not cryptographic.** Filename + exact byte size +
  identical 27-column schema + identical coverage window. Kaggle publishes no hash, so
  byte-identity with the original cannot be proven from here. One open discrepancy: the
  row count recorded during the repo archiver session was ~22,694 vs 24,440 measured in
  the mirror — unresolved; treat the mirror as **MIRROR, never as the Kaggle original**,
  and re-pin if the Kaggle original is ever pulled.
- **Earlier vintage mirrors** (same lineage, 2008–2025 file, 2,370,902 bytes each):
  `isaacsilver13/nba :: data/odds/nba_2008-2025.csv` and
  `Cole-Krudwig/nba-moneyline-betting :: data/nba_games.csv`.
- **What this changes:** the NBA successor's *design* screen (§5 build-order item 7) no
  longer needs the blocked Kaggle workflow — the design baseline is pinnable today via
  the mirror, and via direct SBR (§5.2) for the pre-2023 segment. **What it does not
  change:** the file is date-only consensus/median with mid-file provenance switches —
  it does not cure G2, and no freeze may rest on it.

### 2.3 The Odds API (the-odds-api.com) — documentation verdict

Documented from the vendor's public materials as quoted in published comparisons
(ParlayAPI's comparison page quotes the v4 guide, read 2026-08-25; TheRundown's
comparison checked Oct 13, 2026). No key was used or tested — the held keys
(`SPORTSEDGE_ODDS_API_KEY` ×4, GitHub secrets) are Actions-only by design.

- **Historical endpoint exists and fits G2's shape:** point-in-time snapshots at
  **10-minute intervals from June 2020, 5-minute intervals from September 2022**;
  per-bookmaker odds (40+ books incl. DraftKings and FanDuel), each book entry carrying
  its own update timestamp, snapshot selected by timestamp → this *is* a
  timestamp-authenticated baseline for NBA/NFL/MLB for 2023+ (and back to 2020).
- **Tier requirement:** the historical endpoint is **paid-plans only** (multiple sources
  agree). Published tiers: free 500 credits/mo (no historical); paid $30/mo (20k
  credits), $59 (100k), $119 (5M), $249 (15M). Historical cost: **10 credits × regions ×
  markets per snapshot** — a US 3-market snapshot is 30 credits, so backfill volume, not
  the sticker price, is the real cost driver.
- **Verdict:** *If* any held key already sits on a paid tier, G2's historical leg
  (and G4's, §4) is already paid for and merely un-wired. That fact is **not**
  determinable from public documentation; it takes one account-side usage check in the
  environment where the keys live. Under the FREE-ONLY ruling no new purchase is
  authorized either way — this section is a documentation verdict only.

### 2.4 G2 bottom line

Free timestamped per-book NBA closes for 2023+ do not exist on the searched surface.
The validation baseline remains the forward DK capture archive, exactly as Phase 1
concluded. The design baseline is now pinnable via §2.2/§5.2 without the blocked
workflow.

---

## 3. G1 — Historical player-prop closing lines

### 3.1 MLB — FOUND-ADMISSIBLE candidate: SmartStake (Hugging Face)

**`SmartStake/mlb-player-props`** — "SmartStake MLB Player Prop Odds and Results (2026)".

Verified by sample pulls (not the README alone):

- **Shape:** one row = one book's price for one selection at one minute. 20 parquet
  partitions (`mon=2026-03` … `mon=2026-07`), 901,411,520 bytes total.
- **March part-000 (pulled, parsed):** 1,432,405 rows; columns include `book`, `stat`
  (e.g. `pitcher_strikeouts`), `line`, `over_odds`/`under_odds` (decimal), `snap_ts`
  and `tick_ts` (tz-aware, minute precision), `start_ts` (scheduled first pitch),
  `close_ts`, `is_close`, `outcome_known`, `segment`. 155 distinct `book` labels
  including **DK** (895,066 rows in this partition alone), Pinnacle, FanDuel, Caesars.
  `outcome_known` = 96.9% of rows.
- **June part-000 (pulled, parsed):** 111,148 rows; markets HITS, TOTAL_BASES,
  PITCHER_STRIKEOUTS, HITS+RUNS+RBIS. May/June partitions show 15–40 books per part —
  book coverage varies by partition; DK presence is verified in March and must be
  re-verified per partition at ingestion.
- **Coverage:** late March – early July 2026 (one season). Markets per README + pulls:
  total bases, hits, RBIs, home runs, strikeouts, batting walks. Graded outcomes
  attached (March–June settled at export; July rows ungraded at export).
- **License/terms:** CC BY 4.0; provenance stated as collected from public sportsbook
  and exchange feeds, outcomes from official box scores. Two mirror copies exist
  (`Neonlightzz/mlb-player-props`, `canesyrup/mlb-player-props`, identical file lists) —
  pin the canonical SmartStake repo only.
- **Admission caveats (binding on any use):**
  1. **One season, and it is the season in progress.** The retired MLB batter incumbent
     never had prop lines at all, so this is not data a failed construction saw. For the
     successor (designed Oct 26, 2026, PR #2786) the data predates the design — it may
     serve as the successor's historical screen baseline **only** under a preregistered
     chronological split (e.g. fit Mar–May, validate Jun–Jul) declared before use.
     It is DESIGN/SCREEN data, never a forward clock and never validation of record.
  2. **Two schema generations exist** (README's `book/ts/start_time` vs the observed
     `book/snap_ts/start_ts` + `segment` flags). Admission must pin the *observed*
     schema, require `snap_ts < start_ts` filtering, and specify `segment`
     (ATTACHMENT / HEAVY / LONG_TERM) handling in the screen prereg before any run.
  3. Pins for the four pulled partitions are in `PINS.md`.
- **Full admission-record draft:** `ADMISSION_DRAFT_smartstake_mlb_props.md` (this folder).

This is the single largest gap-fill of the hunt: G1/MLB goes from NO_DATA to a
screenable historical baseline. G1 for the other sports does not move.

### 3.2 NFL — NOT FOUND free; one free-tier commercial surface

- **EndzoneAPI** (verified on its own site, Oct 28, 2026): NFL player props **by
  sportsbook, opening to closing, since 2023** (passing/rushing/receiving yards,
  receptions, TDs, more), 8 books incl. DraftKings, FanDuel, BetMGM, Pinnacle; per-book
  game lines from 2014, game-day snapshots from 2020 (hourly in 2026). 500 free credits
  every month, no card (odds tools cost 10 credits/call ≈ 50 calls/mo free); paid from
  $19/mo. Vendor's own caveat: Pinnacle + three books not captured Feb 9 – Oct 6, 2026.
  **Status:** free-tier surface exists, but it needs an account/key the program does not
  hold, and no signup was performed. Listed here as a free route awaiting an owner
  account act — not an admission.
- **PropLine Hugging Face sample** (`propline/graded-player-props-sample`, pulled and
  parsed): a 14-day graded NFL sample (Sep 2026) that **does** carry bookmaker identity
  and `opening_at` / `closing_at` price timestamps, with opening/closing points and
  prices per player-market (200k+ rows read). REJECTED as a G1 baseline anyway:
  (a) 14 days is a sample, not the multi-season archive G1 requires; (b) the sampled
  book mix is prediction-market/DFS-heavy (e.g. `polymarket_us` in the head rows) with
  DraftKings/FanDuel representation unverified; (c) the full archive is paid → §7.
  (Correction, Oct 28: an earlier draft of this section misstated the sample's schema
  as lacking book/timestamp fields; the fields exist — the depth and book-mix grounds
  above are the operative ones.)
- **Action Network** advertises graded DraftKings/FanDuel props since 2023-24 inside its
  consumer product — not an exportable dataset. Not a source.
- **BetWatch** (blog) describes a private 2026-playoff prop archive built from DFS apps
  (Dabble/Underdog) — unpublished, and DFS lines are not book lines. Not a source.
- GitHub/HF/Kaggle searches surfaced no free NFL prop archive. **G1/NFL stays NO_DATA;
  DK forward capture is the path** (plus the free-tier route above if the owner opens it).

### 3.3 NBA / CFB / CBB props — NOT FOUND

No free historical prop-line archive for NBA, CFB, or CBB props exists on the searched
surface. The Odds API's historical event-odds endpoints document player-prop snapshots
for recent years on paid plans (documentation-level statement only; not pull-verified,
and paid → §7). **G1 stays NO_DATA for NBA/CFB/CBB; forward DK capture only.**

---

## 4. G4 — Timestamped historical MLB game-line archive

### 4.1 NOT FOUND (free)

- **flancast90/sportsbookreview-scraper MLB archive** (pulled and parsed): 25,597 games,
  2011–2021; fields include open/close moneylines, open/close totals with odds, inning
  scores — but `date` is date-only (YYYYMMDD), no book identity, no quote timestamps;
  run-line fields are zeroed in the 2011 sample (spotty early coverage). Same SBR family
  as everywhere else: **design-grade only, REJECTED for G4's timestamp requirement.**
- **`minmaxxxer/mlb-closing-odds-2025`** (Hugging Face, CC BY 4.0): every 2025 game
  (2,430 regular + 47 playoff) with *consensus* opening/closing lines, one row per game.
  Date-only, no book. Design-grade only.
- **`Oronto/baseball-stats-cleaned_oddsportal_mlb`** (Hugging Face): OddsPortal-sourced.
  REJECTED — the program does not use OddsPortal-sourced data (standing ToS rule), and
  no license is stated.
- **SBR MLB Excel family** (date-only; §5.4) and the **Kaggle moneyline-average file**
  (already rejected in Phase 1) close out the free surface.

### 4.2 G4 bottom line

No free timestamped MLB game-line archive exists. The only timestamped route is the
same paid historical-snapshot endpoint documented in §2.3. **Phase D stays
accuracy-only; the 2027 Opening Day forward clock plan is unchanged.**

---

## 5. G5 — SBR archive audit (NCAAB) + direct-archive extension (NBA/MLB/NFL/NHL)

### 5.1 NCAAB audit — COMPLETE

**Location:** classic Excel files `ncaa basketball YYYY-YY.xlsx` under
`sportsbookreviewsonline.com/scoresoddsarchives/ncaabasketball/`, seasons **2007-08
through 2021-22** (15 seasonal files enumerated via Wayback CDX). The live site no
longer serves the files (404 on direct fetch, Oct 28, 2026); the access route is
Wayback Machine snapshots (the 2022-10-20 crawl batch is complete for all seasons).

**Method:** six seasons pulled and parsed (pins in `PINS.md`): 2007-08, 2013-14,
2018-19, 2019-20, 2020-21, 2021-22. Format: two rows per game (V/H or N), columns
`Date (MMDD code), Rot, VH, Team, 1st, 2nd, Final, Open, Close, ML, 2H`; the total is
carried on one row's Open/Close and the spread on the other's; ML is per team.

**Coverage:** full seasons, Nov → early Apr, every year sampled:
3,523 games (2007-08), 3,923 (2013-14), 5,599 (2018-19), 5,329 (2019-20 — ends
2020-03-11, the COVID cancellation, correctly), 3,931 (2020-21), 5,481 (2021-22).

**Missingness:** `Close` non-null ≥ 99.9% in every sampled season; explicit `NL`
(no-line) tokens: Close 0.0–5.4% by season (worst 2013-14), ML up to 3.1%. No silently
blank odds cells of consequence; `NL` is an honest marker, concentrated in
low-major games — a screen must declare its `NL` handling in advance.

**Spot-checks vs known results (championship games):**

| Season | Game | Scores in file | Closing spread | Closing total |
|---|---|---|---|---|
| 2007-08 | Kansas 75, Memphis 68 (OT) | KU 75 ✓ (Memphis row under a variant name string) | — | 146.5 (reported ~147) |
| 2013-14 | UConn 60, Kentucky 54 | 60 ✓ / 54 ✓ | Kentucky −2.5 (reported −2.5, exact) | 135 (reported ~134.5) |
| 2018-19 | Virginia 85, Texas Tech 77 (OT) | UVA 85 ✓ | Virginia −2 (reported −1.5/−2) | — |
| 2020-21 | Baylor 86, Gonzaga 70 | 86 ✓ / 70 ✓, halves exact | Gonzaga −4.5 (reported −4.5, exact) | 159 (reported ~159.5) |
| 2021-22 | Kansas 72, UNC 69 | KU 72 ✓ | Kansas −4 (reported −4, exact) | — |

Every checked score is exact; every checked close is exact or within a half point of
the widely reported close. **Data-quality caveats:** team-name strings vary (353–507
distinct strings per season vs ~350 D1 teams; trailing spaces in 2013-14, e.g.
`Kentucky␠`) — a normalization map is required before any join; one 2008 Memphis row
was not located under its expected name string.

**Verdict: FOUND-ADMISSIBLE as the CBB DESIGN baseline** (upgrading Phase 1's
"candidate, contingent on audit"). It remains date-only with no per-book identity and
no timestamps → the validation leg of G5 is still NO_DATA permanently, and the CBB
validation baseline is DK forward capture from Nov 1, 2026, exactly as planned.

### 5.2 NBA leg — direct archive verified; provenance beats the Kaggle derivative

Seasonal files `nba odds YYYY-YY.xlsx` under `.../scoresoddsarchives/nba/`, 2007-08
through **2022-23** (Wayback CDX; the 2022-23 file's last crawl is 2023-01-23, so that
season is partial at capture). Two files pulled and parsed (pins in `PINS.md`):
2021-22 (2,646 rows = 1,323 games, full season) and 2022-23 (1,328 rows, through
~Jan 22, 2023). Schema adds quarter columns (`1st, 2nd, 3rd, 4th`) to the NCAAB
layout. Spot-checks exact: 2021-10-19 Nets 104 @ Bucks 127 ✓ (total close 233.5 ✓,
Bucks −1.5 ✓); 2022-10-18 76ers 117 @ Celtics 126 ✓ (total close 216, spread close
Boston −3 — both in the reported ranges).

**Provenance comparison (the question asked):** for the pre-2023 segment, **direct SBR
beats the Kaggle derivative** — single publisher, untransformed seasonal files,
pinnable by hash today. The Kaggle file layers transformations on top (signed spread
via `whos_favored`, season/playoff flags, ID columns) and switches provenance mid-file
(ESPN, then SBR median) precisely where the direct archive ends. Recommended citation
practice: design work on ≤2022-23 cites direct SBR (pinned); the 2023+ design segment
exists only in the Kaggle file/mirror and must carry its ESPN/median segment labels.

### 5.3 MLB leg

Direct MLB xlsx listing could not be retrieved from Wayback during this hunt
(three CDX attempts returned empty amid intermittent IA availability; directory naming
unverified) — recorded as **not re-verified**, not as nonexistent. The same source's
MLB data *was* verified via the flancast90 scrape of sportsbookreview.com
(§4.1: 25,597 games, 2011–2021, date-only open/close ML + totals). Either way the MLB
leg is the same date-only SBR family: design-grade, no G4 value.

### 5.4 NFL / NHL legs (one line each)

NFL: the classic archive exists in the same form (seasonal + preseason xlsx verified
in the CDX listing) — date-only SBR family; NFL design closes are already served by
nflverse, so no action. NHL: seasonal xlsx verified in the CDX listing through
2022-23 — same family; NHL was paused at plan time and is design-irrelevant here.

---

## 6. SportsOddsHistory.com — verified: cross-check surface, not a baseline

Verified on the live site and via Sports-Reference's own account of the data
(Nov 2022 / Jan 2019 posts): Covers' Sports Odds History is a free, browsable archive
whose core asset is **NFL point spreads — 100% complete back to 1969, nearly complete
to 1952** (this data literally feeds Pro-Football-Reference), totals complete back to
1978, plus preseason futures, playoff series prices (MLB/NBA/NHL), season win totals,
and futures/props pages.

- **Granularity:** per-game for NFL spreads/totals; **series-level** for MLB/NBA/NHL
  playoffs; futures/win totals are market snapshots, not game lines.
- **Book identity:** none stated — a single presented closing line. **Timestamps:**
  date-only. **Bulk access:** none found — browsable pages only (menus/search), no
  download, no API.
- **Verdict: CROSS-CHECK SURFACE.** Its legitimate use is spot-validating closes in
  other archives (e.g. adjudicating an SBR vs nflverse disagreement on a specific
  game). It is not a baseline and nothing should be bulk-harvested from it.

---

## 7. CLOSED by owner ruling (Oct 27, 2026 ~23:20 CT) — paid sources, one line each

Recorded for completeness; no pricing evaluation performed beyond what was already
public in the hunt's path, and none will be.

- **Scottfree Analytics** — commercial historical odds datasets — CLOSED by owner ruling Oct 27, 2026.
- **Odds Warehouse** — commercial historical odds archive — CLOSED by owner ruling Oct 27, 2026.
- **The Odds Gap** — paid odds/prop archive accruing from Jun/Aug 2026 — CLOSED by owner ruling Oct 27, 2026.
- **Spreadspoke full history** — NFL closing spreads/totals 1966–present (free tier = latest-season sample only) — CLOSED by owner ruling Oct 27, 2026.
- **PropLine full archive / $99 backfill** — graded props, open/close + tick history, all major sports — CLOSED by owner ruling Oct 27, 2026.
- **ParlayAPI paid tiers** — closing-line archive from 2005 + 30M-row prop archive — CLOSED by owner ruling Oct 27, 2026.
- **Olivier / oliviersportsdata Gumroad archives** — timestamped multi-market files (e.g. NFL 2018–2026, 2.8M snapshots, two named books; free samples on GitHub/HF incl. the rejected moneyline-average product) — CLOSED by owner ruling Oct 27, 2026.
- **BigDataBall CBB datasets** — per-season Excel incl. college basketball odds — CLOSED by owner ruling Oct 27, 2026.
- **EndzoneAPI paid tiers** — NFL props/lines depth beyond the free credit tier — CLOSED by owner ruling Oct 27, 2026 (free tier noted in §3.2).
- **The Odds API paid tiers** — the historical-snapshot endpoint of §2.3 — CLOSED by owner ruling Oct 27, 2026 (documentation verdict stands; pre-existing keys' tier is an account fact, not a purchase).
- **Commercial prop archives named in Phase 1** (SportsGameOdds, STAT-API, OddsJam/OpticOdds APIs) — CLOSED by owner ruling Oct 27, 2026.

---

## 8. Net effect on the program

- **G1/MLB:** NO_DATA → screenable historical baseline (SmartStake), pending the
  admission record + preregistered split discipline of §3.1. The MLB batter successor
  (§5 build-order item 9) gains a design-screen path it did not have; its validation
  remains forward DK capture.
- **G5:** design leg upgraded from candidate to **audited** (SBR NCAAB, pinned).
  CBB construction design (build-order item 8) may cite it. Validation leg unchanged.
- **G2:** design access unblocked (mirror §2.2 + direct SBR §5.2); validation leg
  unchanged — forward DK archive or nothing.
- **G4:** unchanged — Phase D accuracy-only, 2027 clock plan intact.
- **G1 NFL/NBA/CFB/CBB:** unchanged — forward capture only (NFL has one free-tier
  commercial surface, §3.2, if the owner ever opens the account).
- Nothing in this hunt touches a frozen artifact, a prereg, or a clock. No engine
  code was written. All pins: `PINS.md`. Admission draft: §3.1's companion file.
