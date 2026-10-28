# ADMISSION RECORD — DRAFT

## SmartStake MLB Player Prop Odds and Results (2026) — Hugging Face

**Status:** DRAFT for owner/lane review. Nothing in this record admits the source by
itself; admission takes effect only when this record is merged with its conditions
accepted. **Scope of admission if approved: DESIGN/SCREEN ONLY** — historical screen
baseline for the MLB batter successor construction (PR #2786 protocol). Never a
forward clock, never validation of record, never "verified CLV."

### Source identity

- Publisher: SmartStake (dataset card cites its study "Sharpest Sportsbooks for MLB
  Player Props", smartstake.app).
- Location: Hugging Face dataset `SmartStake/mlb-player-props`.
- License: **CC BY 4.0** (attribution required).
- Stated provenance: odds collected from public sportsbook and exchange feeds;
  outcomes from official box scores.
- Known mirrors (`Neonlightzz/mlb-player-props`, `canesyrup/mlb-player-props`) are
  NOT admitted; pin the canonical repo only.

### Contents (verified by sample pulls, Oct 28, 2026)

- 20 parquet partitions `mon=2026-03`…`mon=2026-07`; 901,411,520 bytes total.
- One row = one book's price for one selection at one minute:
  `book, player, stat/market, line, side, over_odds/under_odds (decimal),
  snap_ts / tick_ts (tz-aware, minute precision), start_ts, close_ts, is_close,
  outcome_known, segment` (observed schema; see condition 2).
- Markets: total bases, hits, RBIs, home runs, pitcher strikeouts, batting walks
  (observed in pulls: HITS, TOTAL_BASES, PITCHER_STRIKEOUTS, HITS+RUNS+RBIS, + more).
- Books: ~75 claimed; 155 distinct labels observed in the March partition, incl.
  DraftKings (895,066 rows in that partition), Pinnacle, FanDuel, Caesars. Book
  coverage varies by partition (15–40 in May/June parts) — per-partition book census
  is an ingestion requirement, not an assumption.
- Graded outcomes attached; `outcome_known` = 96.9% in the March partition; July
  rows were ungraded at export time.
- Coverage: late March – early July 2026. **One season.**

### Point-in-time safety

- As-of discipline is enforceable from the data itself: every quote carries
  `snap_ts`, every game its scheduled `start_ts`. A screen row is admissible only
  with `snap_ts < start_ts`; the closing price per (book, market, player, side) is
  the last such quote, cross-checked against the `is_close` flag and `close_ts`.
- Outcomes (`result`, `won`) are post-game facts joined on game identity — standard
  walk-forward separation applies; no feature may be built from them.

### Conditions of admission

1. **Preregistered split before first use.** The 2026 season predates the successor
   design (Oct 26, 2026). Any screen must preregister a chronological split
   (e.g. fit Mar–May / validate Jun–Jul) and its per-stat criteria before the data
   is touched for modeling. Data seen in design becomes design data thereafter.
2. **Observed schema is canonical.** The dataset card's schema (`ts`, `start_time`)
   and the files' observed schema (`snap_ts`, `start_ts`, `segment`, …) differ.
   Ingestion pins the observed schema; `segment` values (ATTACHMENT / HEAVY /
   LONG_TERM) must be defined from the data and their handling declared in the
   screen prereg — silently pooling segments is prohibited.
3. **Pin before use.** Full-dataset pin = per-partition sha256 manifest (four
   partitions pinned in `PINS.md`; complete the remaining 16 at ingestion) plus
   the dataset revision. Any upstream revision invalidates prior screen rows
   until re-pinned.
4. **Labels.** All outputs carry DESIGN/SCREEN labels; vs-close figures are
   "vs-close (timestamped, per book)" for this source only — the one source in the
   program whose closes are timestamped — and are still never "verified CLV,"
   which is reserved for forward DK captures under a frozen clock.
5. **Attribution.** CC BY 4.0 attribution to SmartStake in any published artifact.

### What this admission does NOT do

- It does not admit SmartStake data for any other sport or season.
- It does not start, feed, or substitute for the MLB batter forward DK capture
  archive; validation of the successor still requires forward captures.
- It does not rehabilitate the retired MLB batter incumbent, which never had this
  data and stays retired.
