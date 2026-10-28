# DESIGN AMENDMENT 1 (DRAFT) — PGA Tour tournament matchups (H2H): reference (b) substitution for the Leg 1 screen

**Status: AMENDMENT DRAFT — FOR OWNER / DESIGN REVIEW. NOT ADOPTED, NOT
FROZEN, NOT IN FORCE.** This amendment drafts a change to
`PGA_H2H_MATCHUPS_DESIGN_PREREG_DRAFT.md` (same directory), which is itself
a DESIGN + DRAFT PREREGISTRATION. Landing this document changes nothing:
the design text stands exactly as written until the owner adopts this
amendment in a separate recorded act, and freezing remains the owner's act
under the design's own header. Nothing in this document starts a clock,
runs a screen, or creates a PLAY. All staking language is PAPER / research
only.

Amends: §6 (Leg 1) of the design of record, one clause only (§2 below).
Answers: gap **G-PGA-1** as recorded in PR #2886 (merged 2026-10-28,
merge commit `f013e96f0`), packet `research/pga_h2h_screen_20261028/`.

## 1. The failure it answers (G-PGA-1)

The Leg 1 historical calibration screen was attempted on 2026-10-28 and
recorded **NOT_EXECUTABLE** (PR #2886, `SCREEN_REPORT.md` §3b,
`owgr_probe.json`). No criterion was run, no fitting or simulation was
performed, and no substitute data was used. The decisive gap:

- Reference (b) needs OWGR **points** per player for each test event's
  week.
- **owgr.com archive paths no longer serve the payload.** The weekly PDF
  URLs (e.g. `https://www.owgr.com/archive/PastRankings/2025/Rankings/owgr14f2025.pdf`)
  return HTTP 200 with `Content-Type: text/html` — a 147,450-byte Next.js
  application shell beginning `<!DOCTYPE html>`, byte-count identical
  across different years and weeks (2025 week 14 sha256 `cebfc8ab…`;
  2020 week 37 sha256 `61a7f957…`).
- **The Wayback Machine never archived the payload.** CDX shows captures
  of the weekly PDF URLs, but every one is the http→https 301 redirect
  stub (344–616 bytes, identical content digest
  `3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ`); snapshot downloads from the
  screening environment are additionally rate-blocked (HTTP 429).
- Not attempted, by law: OWGR's undocumented internal site API (and it
  serves current rankings, not the 2023–2025 weekly archive), and the
  paid DataGolf API (closed NO under the owner's free-only law; the
  design itself forbids depending on it).

The same attempt established that the failure is confined to reference
(b): the DataGolf free past-results archive — the construction's inputs
(round scores, per-round strokes-gained) and reference (a)'s inputs
(outright Open/Close odds) — was pulled in full (780/780 pages, HTTP 200,
sha256-pinned in `dg_pages_manifest.json`) and is sufficient
(`SCREEN_REPORT.md` §3a). What is missing is any free, pinnable source of
OWGR weekly **points**. Per-event OWGR **rank** is published on the same
admitted DataGolf pages; the attempt declined to substitute it silently,
because the design says points and substituting rank is a criterion edit
— the owner's act. This amendment is that act, drafted.

## 2. The text it replaces

Design §6, Leg 1, defines the references in one sentence (verbatim):

> References: (a) a market proxy — pairwise probabilities implied by the
> DataGolf past-results **outright Close odds** (field-normalized); (b) an
> OWGR-points-implied reference rating.

This amendment replaces exactly the clause **"(b) an OWGR-points-implied
reference rating"** with:

> (b) an OWGR-rank-implied Bradley–Terry reference rating, as defined in
> Amendment 1 to this design.

No other word of §6 changes. Reference (a), the pass criteria, the
chronology, and every other section of the design are untouched (§6 of
this amendment lists them).

## 3. The replacement reference (b′)

### 3.1 Field selection — measured, not assumed

Each DataGolf past-results page embeds its full record as JSON
(`reload_data`); each player row carries `owgr_rank`, `dg_rank`, and
`dg_pts`. The three candidate fields were measured on 2026-10-28 over the
hash-verified #2886 pull store (780/780 pages reproduce their manifest
sha256) and over a fresh 36-page stratified re-pull (6 pages per season,
2020–2025; 4,785 rows). Findings:

- **`owgr_rank` — EXISTS and is usable.** Valid (an integer ≥ 1) on
  16,567 of 19,630 rows (84.4%) across the deduplicated, identity-matched
  event universe (157 unique events; per-season validity 81.1%–86.9%).
  The only invalid values in the corpus are the sentinels `−9999`
  (2,841 rows) and `−9998` (222 rows) — no other malformed values exist,
  so the validity rule in §3.2 is exact, not defensive. The missing
  ~15% are players the OWGR did not rank that week (amateurs, invitees,
  players outside the ranked list).
- **`dg_pts` — EXISTS as a key, DISQUALIFIED as a reference input, on two
  independent grounds.** (i) *It is an outcome, not a rating:* on the
  2025 Masters page the largest `dg_pts` belongs to the winner
  (McIlroy, 28.0, finished 1st); Scheffler — `dg_rank` 1, `owgr_rank` 1 —
  holds 6.9699 after finishing 4th, and Rose (`dg_rank` 96) holds
  13.8649 after finishing 2nd. The field tracks the player's finish in
  that event, i.e. points earned **from** the event. Using it as a
  pre-event reference would be lookahead, not a substitute rating.
  (ii) *Coverage:* non-sentinel on only 50 of 95 rows on that same page
  and on only 38.5% of rows in the fresh sample. The #2886 report's
  unblock note floated `dg_pts` as a candidate without inspecting its
  semantics; this amendment records the correction.
- **`dg_rank` — exists (valid on 90.2% of sampled rows) but is not
  used.** It is DataGolf's proprietary ordering; reference (b)'s role in
  the design is to represent the *official* world ranking (the slow,
  public prior the construction claims to beat), which `owgr_rank` does
  and `dg_rank` does not. Noted here so the choice is on the record.

### 3.2 Definition (complete; no further choices are needed to implement)

For each event *e* in the screen universe (composite `(event_id, year)`
keys per design §5; the deduplicated, identity-matched archive):

1. **Input.** For each player row on *e*'s pinned DataGolf page, read
   `owgr_rank`. A value is **valid** iff it is an integer ≥ 1. Any other
   value (the corpus's `−9999`/`−9998` sentinels, or an absent key)
   means the player has **no rank** for *e*.
2. **Strength.** Player *i*'s strength in *e* is
   `s(i) = r_i^(−α)`, where `r_i` is *i*'s valid rank and `α > 0` is the
   single scale parameter estimated under step 4.
3. **Pairwise probability.** For players *i*, *j* with valid ranks,
   the reference's probability that *i* finishes ahead of *j* is the
   Bradley–Terry form
   `P(i ahead of j) = s(i) / (s(i) + s(j)) = r_j^α / (r_i^α + r_j^α)`.
   Equal ranks yield exactly 0.5. (Illustration only, at α = 0.5: the
   2025 Masters page carries McIlroy at rank 2 and Rose at rank 39, so
   the reference prices McIlroy ahead of Rose at
   `39^0.5 / (2^0.5 + 39^0.5) ≈ 0.815`.)
4. **Scale estimation (out-of-sample, mirroring §6's refit cadence).**
   For test season *Y* ∈ {2023, 2024, 2025}, `α_Y` is the
   maximum-likelihood estimate over the **same fit window §6 assigns the
   construction for that season** (fit ≤2022 for 2023; ≤2023 for 2024;
   ≤2024 for 2025): over every unordered pair of players in every fit-
   window event where **both** players hold valid ranks **and** the
   archive records a decided (non-tied) finish between them, accumulate
   `log P(player who finished ahead, per step 3)`. `α_Y` maximizes this
   sum over α ∈ [0.01, 2.00]; the objective is a sum of logistic
   log-likelihoods linear in α, hence concave, so the maximum is unique
   and is located by golden-section search until the bracket is narrower
   than 1e-6 — deterministic, with no optimizer freedom. Tied pairs are
   excluded from the fit, per step 5. The fitted `α_Y` values are
   reported in the screen's run record.
5. **Scoring set for criterion 2.** A test-season matchup enters the
   criterion-2 comparison iff it is a screen matchup under §6 (both
   players priced by the construction) **and** both players hold valid
   ranks on that event's page. The candidate's log loss and reference
   (b′)'s log loss are computed over this identical set. Tied finishes
   are excluded from log-loss scoring for every probability source,
   with tie mass reported — the design's own §4.4 convention (the priced
   comparison is conditional on a non-tied finish), applied to Leg 1
   scoring as a clarification, not a new rule. Measured headroom: pairs
   with both ranks valid number 161,012 (2023), 170,476 (2024) and
   167,977 (2025) per season **before** the priced-player restriction —
   two orders of magnitude above criterion 4's 1,500-per-season floor;
   the executor reports the final restricted count per season in the
   run record.

### 3.3 What the substitution costs (disclosed, for the owner's decision)

The original (b) was a cardinal, externally published rating used
parameter-free (probability ∝ published points). The substitute keeps
the same governing body's ordering and the same Bradley–Terry form, but
rank is ordinal: the power curve in step 2 is what gives it cardinal
meaning, and its one parameter is estimated (strictly out-of-sample,
step 4) rather than published. Two consequences the owner accepts by
adopting: (i) reference (b′) is minimally fitted where (b) was purely
published; (ii) rank discards the published points *gaps* between
adjacent ranks — the power curve restores an average gap shape, not the
week-specific one. If the owner prefers zero fitted parameters, fixing
α = 0.5 a priori (the power that best matches the historical OWGR
points-versus-rank curve shape) is the alternative — **that variant is
a separate owner decision and is not this amendment's definition.**

## 4. Point-in-time discipline

- **Ranks are read only from the test event's own pinned page** — never
  from a later event's page, a rankings page, or a carried-forward
  value. The page is the event's own published field record.
- **The pages carry as-of-event values, verified empirically:** on 2020
  pages, Molinari's `owgr_rank` is 20, Kuchar's ranges 17–23 and Day's
  34–51 — their contemporaneous 2020 standings, not their 2026
  standings (all three stand far lower today); Molinari's values on
  2021 pages (130, 92, 173 across the season) track his real decline.
  A backfilled snapshot would show one later rank on every page; the
  corpus shows the opposite. Residual caveat, stated plainly: DataGolf
  publishes no methodology note for these fields; the as-of reading is
  empirical, established by the spot checks above, and the admission act
  (§5) should re-verify one spot check when it pins the corpus.
- **The scale parameter is fitted only on strictly earlier seasons**
  (step 4 uses §6's own fit windows). No test-season outcome, rank, or
  page from season *Y* enters the reference that prices season *Y*.
- **Design §5 stands unchanged** — features from rounds completed before
  the first tee time, composite `(event_id, year)` keys everywhere,
  withdrawal handling as written.

## 5. What remains untouched (exhaustive)

Everything in the design except the single clause replaced in §2:

- §6 Leg 1 chronology: fit ≤2022 → test 2023; refit ≤2023 → test 2024;
  refit ≤2024 → test 2025. Test seasons unchanged.
- Reference (a): the outright-Close market proxy, field-normalized,
  exactly as designed.
- The pass bar, word for word: pooled H2H log loss **strictly better
  than both references** (with (b) now read as (b′)); calibration error
  ≤ 0.05; ≥ 1,500 test matchups per season. No threshold moved, none
  added, none removed.
- The construction (§4) in full: SG skill window and shrinkage, course
  fit, variance, 100,000-event simulation, UNPRICED below 40 measured
  rounds.
- §5 point-in-time rules in full.
- Leg 2 in full (forward DraftKings capture; ≥ 25 events and ≥ 500
  graded rows; CLV > 0; ROI > 0; log-loss delta vs the DK no-vig close
  ≤ 0.0), and §7's multiplicity policy (α = 0.05 / k, primary test =
  the Leg-2 log-loss delta), capture scope, and owner-decision flags.
- The family's state: NO_CONSTRUCTION → DESIGN ONLY. This amendment
  does not freeze the design, admit any source, or run any screen.

## 6. Executability checklist for a Leg 1 re-run

**Now in hand (given owner adoption of this amendment):**

- ✅ A constructable reference (b′), defined end-to-end from fields
  verified present on the admitted pages (§3), with its comparison-set
  volume measured at ~100× the criterion-4 floor per test season.
- ✅ The input corpus: 780/780 DataGolf pages pulled and sha256-pinned
  (manifest in the #2886 packet); the pull store was re-verified
  against every pin on 2026-10-28 (780/780 match).
- ✅ Construction and reference (a) inputs proven sufficient by #2886
  (round scores + per-round SG parse on all pages; outright Close on
  94.7–95.6% of test-season rows).

**Still blocking (neither is cured by this amendment):**

- ⛔ **Adoption.** This amendment is a draft. Criterion 2 as designed
  remains unexecutable until the owner adopts the substitution in a
  recorded act (and the design itself remains an unfrozen draft —
  freezing is a further owner act, per the design's header).
- ⛔ **G-PGA-2 — the design's own admission precondition.** Design §7:
  the DataGolf free archive needs a pin/hash admission before any
  screen runs on it. The #2886 manifest is the raw material; granting
  the admission is a separate governed act. One finding that act must
  decide: **page bytes drift between pulls** — a fresh 36-page re-pull
  on 2026-10-28 matched 0/36 byte pins (e.g. the 2025 Masters page grew
  by 24 bytes: 395,485 → 395,509), while the extracted `reload_data`
  content was verified identical (95 rows; the packet's 3-row fixture
  reproduced field-for-field). The admission should therefore either
  adopt the surviving pull-store bytes as the pinned corpus or pin the
  extracted content per page — not assume a future re-pull reproduces
  the 2026-10-28 bytes.
- ⛔ **The screen implementation does not exist yet.** PR #2886
  deliberately stopped at precondition verification (no fitting, no
  simulation). A re-run requires the §4/§6 executor (fit, simulate,
  score, including reference (b′) per §3.2) to be built and reviewed —
  ordinary executor work under the design, named here so the checklist
  is complete.

*End of amendment draft. Prepared 2026-10-28. Evidence states: the
G-PGA-1 record is PR #2886's, merged and hash-pinned; the field census,
`dg_pts` semantics, point-in-time spot checks, and byte-drift findings
are this draft's own measurements of 2026-10-28 over the hash-verified
pull store and a fresh stratified sample, reproducible from the packet's
`parse_dg_pages.py` extraction. Nothing here is a screen result.*
