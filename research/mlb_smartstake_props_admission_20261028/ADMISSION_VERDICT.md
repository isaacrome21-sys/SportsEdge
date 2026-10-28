# ADMISSION VERDICT — SmartStake MLB Player Prop Odds and Results (2026)

**Verdict: ADMITTED — DESIGN/SCREEN ONLY.**

Executed Oct 28, 2026 (America/Chicago) against the admission draft in
`research/gap_source_hunt_20261027/ADMISSION_DRAFT_smartstake_mlb_props.md` (PR #2850).
The draft's bars were tested one by one against the canonical source, live, with the
full dataset pulled and hash-pinned. **This admission rests on the measurements in
this record, not on the hunt's.** The hunt's contents/schema/census claims about
this dataset do not reproduce (see §4) and are superseded by §2–§3 below.

## 1. Admitted scope (exact)

- **Source:** Hugging Face dataset `SmartStake/mlb-player-props`, pinned at revision
  `7cedfd3fe29f2de4f675039410a48160739323fc`, CC BY 4.0, canonical repo only
  (mirrors `Neonlightzz/…` and `canesyrup/…` are NOT admitted).
- **Use:** DESIGN/SCREEN ONLY — historical screen baseline for the MLB batter
  successor construction (PR #2786 protocol). Never a forward clock, never
  validation of record, never "verified CLV." Vs-close figures from this source are
  labeled **"vs-close (timestamped, per book)"** — for this source only.
- **Seasons:** one — 2026, games 2026-03-21 → 2026-07-05. No other season exists
  in the source; no other sport is admitted.
- **Markets (canonical names, all six):** player bases, player hits, player rbis,
  player home runs, player strikeouts, player batting walks.
- **Books:** per-book rows; 75 distinct book labels dataset-wide; DraftKings
  (`draftkings`) present in **all 18 partitions**, 44,368,757 rows total.

## 2. Live source verification (2026-10-28)

- Dataset is public, not gated, no account, no payment — free-only law satisfied.
  License on the live record: `cc-by-4.0`.
- Revision history: 4 commits, all 2026-07-09; data files uploaded once
  (commit `049dd4caeb56`) and never revised. `usedStorage` = 901,411,520 bytes,
  exactly the pulled parquet total.
- The publisher's study ("Sharpest Sportsbooks for MLB Player Props",
  smartstake.app) exists and describes this exact release: "600M+ MLB prop line
  movements across 75 sportsbooks and exchanges," six prop types, a "Get the data"
  link to this dataset. Measured: **621,391,637 rows, 75 books, six markets** —
  the study's claims and the bytes agree.
- All 18 partitions were pulled at the pinned revision and accepted only when
  size **and** sha256 equal the canonical LFS oid published at that revision
  (transport untrusted-but-verified). 18/18 PIN_MATCH. Data bytes are not
  committed; they are kept at `~/workspace/smartstake_admission_20261028/pulls/`
  and re-pullable via `pull_smartstake_mlb_props.py` in this packet.

## 3. The draft's bars, tested one by one

1. **Provenance — PASS.** Card + study + bytes mutually corroborate (counts in §2).
   Outcomes are joined on `game_id`: across all books, the same
   (game, player, market) selection carries **one identical `result` in
   93,929 of 93,929 graded selection groups — 0 disagreements.** That is the
   signature of a single official-box-score outcome join, not per-book invention.
2. **Point-in-time safety / lookahead — PASS, stronger than drafted.** The draft
   assumed a `snap_ts < start_ts` filter over an `is_close` flag; the canonical
   schema needs neither: **every one of the 621,391,637 quotes satisfies
   `ts < start_time` — 0 violations.** There are no post-start quotes in the
   dataset at all. The closing price per (book, market, player, line, side) is
   therefore unambiguously the last quote, matching the dataset card's own
   closing-line recipe. The only post-game fields are `result`/`won`; no other
   lookahead column exists in the schema.
3. **Coverage — PASS with one declared caveat.** Games 2026-03-21 → 2026-07-05;
   all six claimed markets present at scale (bases 197.1M rows, hits 158.0M,
   RBIs 115.9M, home runs 88.2M, strikeouts 36.2M, batting walks 26.0M).
   Graded outcomes: `result` non-null on 82.9–96.0% of Mar–Jun rows and **0.0%
   of July rows**, exactly as the card states (July is odds-only). **Caveat:**
   June covers 243 distinct games vs 368 (April) and 376 (May) — June is a
   partial month in the export, and July is five days (59 games). Any screen
   design must declare its handling of the thinner June/July tail in advance;
   pooled "validate Jun–Jul" designs inherit a ~300-game validation window,
   not a two-full-month one.
4. **Book identity — PASS.** Every row carries a stable book label; per-partition
   census measured and recorded in `census.json` (48–70 books per partition;
   DraftKings 2.03M–2.98M rows in every partition). The draft's requirement of a
   per-partition book census at ingestion is satisfied by that measurement.
5. **Timestamp quality — PASS.** `ts` is minute-aligned on **100%** of rows
   (0 off-minute values in 621M), matching the card's minute-precision claim.
   `ts` and `start_time` are timezone-naive in the files and declared UTC by the
   card; nothing in the bytes contradicts that, and all handling under this
   admission treats them as UTC (declared here so no consumer has to guess).

## 4. Corrections to the draft (recorded, not silently absorbed)

The draft described a different artifact than the canonical dataset:

- **Partitions: 18, not 20** (the repo holds 20 files total, incl. README.md and
  .gitattributes). Parquet bytes 901,411,520 — the draft's total was right.
- **Schema: the files carry the dataset-card schema exactly** —
  `game_id, start_time, player, market, line, side, book, ts, odds, result, won`.
  The draft's "observed schema" (`snap_ts`, `tick_ts`, `close_ts`, `is_close`,
  `outcome_known`, `segment`, paired `over_odds`/`under_odds`) **does not exist
  in the canonical files and never has** (files uploaded once, 2026-07-09,
  never revised — §2). Draft condition 2 is therefore superseded: this record
  pins the actual schema, and the `segment`-handling clause is void (no such
  column). Market/book names are the card's (`player bases`, `draftkings`, …),
  not the draft's codes (`TOTAL_BASES`, `DraftKings` as a raw label).
- **Scale: March part-000 holds 26,223,713 rows, not the hunt's 1,432,405.**
  The hunt's 155-book census and per-partition row counts describe the same
  unknown artifact as its schema; both mirrors carry byte-identical files to
  canonical, so they do not explain the divergence either.
- **Hunt pins (PINS.md): 1 of 4 reproduces** (`mon=2026-03/part-000.parquet`).
  The other three match no file on the canonical repo, its parquet-conversion
  branch, or either mirror. Draft condition 3 (pin before use) is executed by
  THIS packet instead: `admission_manifest.json` pins all 18 partitions from
  canonical pulls at the pinned revision, with the reconciliation recorded in
  the manifest.

## 5. Draft conditions — disposition

1. **Preregistered split before first use — CARRIED as a binding condition.**
   The 2026 season predates the successor design (Oct 26, 2026). No modeling use
   is authorized until the successor screen preregisters its chronological split
   (e.g. fit Mar–May / validate Jun–Jul, subject to the §3.3 June caveat) and its
   per-stat criteria. Data seen in design becomes design data thereafter.
2. **Observed schema is canonical — SUPERSEDED by §4.** The pinned schema is the
   card schema as measured; consumers must not code against the hunt's schema.
3. **Pin before use — EXECUTED** (`admission_manifest.json` + manifest test).
   Any upstream revision invalidates prior screen rows until re-pinned.
4. **Labels — CARRIED as a binding condition** (DESIGN/SCREEN labels;
   "vs-close (timestamped, per book)" for this source only; never verified CLV).
5. **Attribution — CARRIED.** CC BY 4.0 attribution to SmartStake in any
   published artifact.

Nothing here rehabilitates the retired MLB batter incumbent (it never had this
data and stays retired), feeds or substitutes for the forward DK capture archive,
or admits SmartStake data for any other sport or season.

## 6. G1 after this verdict

G1 (historical prop closing lines) moves for exactly one family: **MLB player
props** — batter props (bases, hits, RBIs, home runs, batting walks) and pitcher
strikeouts gain a timestamped, per-book historical baseline, including DraftKings,
for the 2026 season, usable as the MLB batter successor's design screen under a
preregistered split. Everything else is unchanged: G1 remains NO_DATA for NFL,
NBA, CFB, and CBB props, and MLB game lines (G4) remain unanswered — those stay
forward-capture-only, and validation of any successor still requires forward DK
captures under a frozen clock.
