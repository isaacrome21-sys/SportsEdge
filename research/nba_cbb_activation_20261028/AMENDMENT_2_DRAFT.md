# AMENDMENT 2 (DRAFT) — CBB_TORVIK_EFFICIENCY_V1 and CBB TEAM TOTALS: completion of the §5 forward terms (pick rule, interval construction, close validity)

**Status: DRAFT — NOT ADOPTED. This draft changes no term by
landing, freezes nothing, and counts nothing.** It is drafted in
the manner of Amendment 1 (`AMENDMENT_1.md` in this directory,
PR #2883): it becomes part of the preregistrations it completes
only by the owner's recorded adoption act, with its own
independent review closed on the exact head carrying the
adoption, followed by each family's own freeze act (whose
remaining prerequisites — data gate (iii), capture delivery
proven on the opening slates, and the forward-runner build,
finding F-1 — are untouched by this draft and still owed).
Until adoption **and** the freeze acts, both families remain
**DESIGN ONLY**, `verified_play = false`, PAPER / 0u, and no
game, row, or slate counts toward either test.

**What this amendment is.** The freeze packages for both
families (`research/cbb_torvik_efficiency_screen_20261028/PREREG_FINAL.md`
and `research/cbb_team_totals_screen_20261028/PREREG_FINAL.md`,
PRs #2903 / #2904) transcribe the designs' §5 forward terms
verbatim and record, in their §8, the same three **blocking
gaps** — the places where §5 does not reach, so that two honest
executors would compute different verdicts from the same rows:

- **G-1 — No pick rule for the market leg.** §5 requires
  "CLV > 0 and ROI > 0 vs the closing line at captured prices",
  but no term states which rows are selections, which side of a
  row is taken, or the stake convention. ROI is undefined
  without them, and CLV needs a designated side per row.
- **G-2 — No interval construction for the accuracy leg.** §5
  requires "CI upper < 0" but states no method, no resample
  count, and no confidence level for the forward test. (The §3
  design screen's paired season-block bootstrap is a screen
  term over eight historical season blocks; a single
  in-progress forward season has no season blocks, so it does
  not transfer by its own words.)
- **G-3 — No close-validity or missing-close rule.** §5 grades
  rows "against the FINAL capture's closing line" but states
  no rule for a row whose game has no FINAL capture, a
  one-sided close, or a stale close. (The framework defaults
  carried in the packages' CONFIG_DRAFT.json —
  `max_clv_missing_share` 0.2, `close_max_age_minutes` 60 —
  are framework values with no preregistration force until an
  amendment fixes the families' own rule.)

This amendment supplies exactly those three missing pieces of
machinery, and nothing else. **It does not alter any existing
§5 criterion, threshold, or leg** — not the population, not the
data gates, not the accuracy pairing, not "CI upper < 0", not
"CLV > 0 and ROI > 0", not the verdict gate of ≥ 40 distinct
graded games, not the single-review rule. §5 of the amendment
indexes every added term to its provenance: **adopted-from**
(the program's own frozen form, carried unchanged),
**adapted-from** (a frozen form adjusted to CBB, with the
adjustment and its reason stated), or **NEW** (no program form
exists; the narrowest term that makes the leg computable).

**Drafting basis.** Where a program form exists, this amendment
uses it: the frozen NFL team-totals preregistration
(`research/nfl_team_totals_forward_20261028/PREREG_NFL_TEAM_TOTALS_FORWARD_V1.md`,
cited below as "NFL TT") — its §5 pick-rule shape, §7
close-validity rules, §8 refusal codes, §9 game-cluster
bootstrap, §4 review discipline, and the NFL props v1.1
moved-row bucket rules its §6 incorporates. The freeze
packages deliberately did **not** import those terms, because
they are that family's frozen terms, not these families'; this
amendment is the owner's-act channel the packages name for
supplying them, and it adopts/adapts them expressly, term by
term, rather than by silent inheritance.

---

## 0. One amendment for both families — and why

One amendment document names both families. The packages'
language supports this, in four parts. (i) The team-totals
family has no standalone §5: its design
(`CBB_TEAM_TOTALS_1H_DESIGN.md` §1) states its forward terms
**by inheritance** from the parent design's §5, so the terms
being completed are literally the same text. (ii) Both
packages record the three gaps in materially identical words;
there is one defect, stated twice, not two defects. (iii) The
machinery that completes them is family-independent in form
(gap vs line, cluster bootstrap over games, FINAL-capture
validity); what differs per family is only parameterization —
markets (SPREAD / TOTAL vs TEAM_TOTAL), the paired accuracy
statistic, and the residual scale behind the pick threshold —
and each is stated per family where it applies. (iv) Both
packages bind the same multiple-testing discipline and the
same seed (20261028), so the interval construction is stated
once, identically. Each family's adoption, freeze act, clock,
and verdict remain its own: a family verdict is never
inherited from a sibling leg (the team-totals package's own
rule), and nothing in this amendment joins the two tests.

*Provenance: NEW (organizational choice), justified above from
the packages' own text.*

## 1. G-1 — Pick rule, designated side, CLV set, and ROI

### 1.1 Gaps and designated sides

For every priced row, the forward runner records the model's
emitted mean, the entry line from the T-1H capture, and the
**gap**, defined per market in the model's own units:

- **SPREAD** (efficiency family): `gap = μ_M − M_mkt`, where
  `μ_M` is the construction's emitted expected margin (home
  points − away points, home-court term included, per the
  construction of record) and `M_mkt` is the market-implied
  margin from the entry line — the margin the home team must
  exceed to cover (home −4.5 ⇒ `M_mkt` = +4.5). The designated
  side is HOME if `gap > 0`, AWAY if `gap < 0`.
- **TOTAL** (efficiency family): `gap = μ_T − entry_line`,
  where `μ_T` is the construction's emitted expected game
  total. The designated side is OVER if `gap > 0`, UNDER if
  `gap < 0`.
- **TEAM_TOTAL** (team-totals family; one row per team per
  game): `gap = μ_team − entry_line`, where `μ_team` is the
  construction's emitted expected points for that team. The
  designated side is OVER if `gap > 0`, UNDER if `gap < 0`.

A row with `gap = 0` has no designated side: it is never
PICKED, is excluded from the market leg, and is counted as
`GAP_ZERO`.

*Provenance: adapted-from NFL TT §5/§6c — the gap is the
model-mean-minus-entry-line form of NFL TT §5, restated per
market because CBB's spread is a two-sided margin market
rather than a team total; the `GAP_ZERO` handling is
adopted-from NFL TT §6c/§8.*

### 1.2 Pick thresholds — derived from the CBB screens' own residual scale

A row is **PICKED** on its designated side when `|gap|` meets
the market's threshold; otherwise it is **PASSED**. The
thresholds follow NFL TT §5's form — a fixed point threshold
set at ≈ 0.2σ of the quantity being forecast, where NFL TT
justified its ±2.0 by σ ≈ 10.2 for an NFL team score. CBB's σ
differs per market and is derived here from **the CBB design
screens' own pooled candidate residuals**, the only
preregistered residual scale these families have. The screens
publish pooled candidate MAEs (attempt 4, PR #2891:
`screen_result_attempt4.json`; team totals, PR #2892:
`screen_result.json`); neither publishes a residual SD, so σ̂
is read from the MAE under the normal-residual identity
`E|X| = σ·√(2/π)`, i.e. `σ̂ = MAE × √(π/2) = MAE × 1.2533141`:

| Market | Pooled candidate MAE (screen) | n | σ̂ = MAE × 1.2533141 | 0.2σ̂ | **Threshold** | Threshold ÷ σ̂ |
|---|---|---|---|---|---|---|
| SPREAD | 8.899248 | 23,564 fixtures | 11.1536 | 2.2307 | **2.2** | 0.197 |
| TOTAL | 13.811724 | 23,564 fixtures | 17.3104 | 3.4621 | **3.5** | 0.202 |
| TEAM_TOTAL | 8.341139 | 47,128 team-games | 10.4541 | 2.0908 | **2.1** | 0.201 |

Each threshold is 0.2σ̂ stated to the nearest 0.1 point, so
each sits within ±0.003σ̂ of the 0.2σ̂ stringency of the NFL
form. **Disclosure of the reading:** the normal-residual
identity is a stated reading of the published MAEs, not a
screen output. If the true residual distributions are heavier
tailed than normal, the true σ exceeds σ̂ and these thresholds
are, if anything, the *less* stringent choice relative to a
true 0.2σ — the direction of the reading's error is disclosed
rather than hidden. The thresholds are constants of this
amendment: if a future version re-derives σ̂ from published
residual SDs, that is a new version scored from its own
adoption forward, never a silent continuation (the version
rule of NFL TT §11, adopted-from).

*Provenance: adapted-from NFL TT §5 — same 0.2σ construction
and same "changing the threshold is a new version" rule; the
σ̂ values and the MAE-to-σ reading are NEW derivations from
this family's own screen record, stated in full above.*

### 1.3 CLV — set, side, and definition

CLV is computed on the **designated side** of a row, and the
market leg's CLV figure is the **mean CLV over PICKED rows
whose valid close is at the entry line** (§3 governs validity
and moved rows):

`CLV_row = p_close(side) − p_entry(side)`,

each probability the multiplicative de-vig (no-vig) implied
probability of the designated side from a real matched
two-sided pair at the **same line** — the entry pair from the
T-1H capture, the close pair from the valid FINAL capture.

Two deliberate non-imports, stated so the leg is not quietly
stiffened: (i) NFL TT §6c additionally requires picked mean
CLV to exceed PASSED-row mean CLV; that is a **pass
criterion** of the NFL family, not machinery, and it is
**not** imported — §5's market leg as written is "CLV > 0",
read on the PICKED set that the leg's ROI half already
requires. (ii) §5 states no interval for the market leg; the
leg is read on the point estimates exactly as written. The §2
interval construction is **reported alongside** the market
leg's figures at the review for information; it is not a
criterion and cannot change the leg's reading. If no PICKED
row has a valid same-line close (all moved or missing), mean
CLV is undefined and the market leg does not pass.

*Provenance: adopted-from NFL TT §7 (CLV definition, same-line
matched pairs, multiplicative de-vig — the de-vig form is the
one NFL TT §2/§7 record) and §6c (CLV scored on the designated
side per row); the PICKED-set reading of §5's "CLV > 0" is NEW
— the narrowest reading that makes the leg's two halves share
one selection set — with the non-imports stated above.*

### 1.4 ROI — stake convention and settlement

ROI is computed over the same PICKED set, at flat stakes:

- **Stake:** exactly 1 unit per PICKED row, at the row's entry
  price for the designated side from the T-1H capture (PAPER /
  0u — these are accounting units of the test, not wagers).
- **Settlement:** against the game's final score (overtime
  included, per DraftKings settlement), from the admitted
  schedule substrate of record (the hoopR/ESPN schedule
  universe joined on the identity crosswalk's IDs — the same
  finals source the design screens graded against). A PICKED
  row **wins** if the designated side covers the entry line,
  **loses** if it does not, and **pushes** if the final lands
  exactly on the entry line (whole-number lines only). Net per
  row: win ⇒ the entry price's profit on 1 unit (e.g. −110 ⇒
  +100/110); loss ⇒ −1; push ⇒ 0.
- **ROI** = (sum of net units over all PICKED rows) ÷ (number
  of PICKED rows). Pushes are counted and reported, contribute
  0 net, and remain in the denominator.
- A postponed, suspended-and-not-completed, or cancelled game
  is **void**: its rows are excluded from every leg and
  counted in a `VOID` report. If the settlement source lacks a
  final for a game at review, its rows are
  `RESULT_UNAVAILABLE`: excluded and counted, never filled.
- If the PICKED set is empty at the review, ROI is undefined
  and the market leg does not pass. No minimum picked count is
  added as a gate (§4 states why); the leg's arithmetic, not a
  new threshold, is what an empty set fails.

*Provenance: the flat 1-unit stake and the ROI form are NEW
(no CBB or NFL TT text states an ROI denominator — NFL TT has
no ROI leg); the settlement, void, push, and
RESULT_UNAVAILABLE rules are adapted-from NFL TT §3, with the
settlement source changed to this family's admitted schedule
substrate (the NFL source, nflverse schedules, does not exist
for CBB) and overtime stated per DK settlement as NFL TT §3
states it.*

### 1.5 Row record (what the runner must commit)

The legs above are auditable only if the per-row record
commits, before tip, create-only: game (crosswalk identity),
market, the model's emitted mean, **the simple ratings
baseline's emitted value for the same row** (the §5 accuracy
leg's baseline, recomputed forward and recorded at pricing
time — the analog of NFL TT §2's requirement that Lane A's
emitted means be recorded in the run record), the entry line,
both entry prices with the capture timestamp, the gap, the
designated side, the pick classification, and the entry no-vig
probabilities. §5's terms are unchanged by this list; it is
the recording machinery the frozen-form families use to make
their legs reproducible.

*Provenance: adapted-from NFL TT §2 (committed per-row record;
baseline means recorded at entry), restated for this family's
baseline and capture form.*

## 2. G-2 — Interval construction for the accuracy leg

The "CI" of §5's accuracy leg ("paired spread/total MAE vs
the §1 simple ratings baseline recomputed forward, CI upper
< 0"; for team totals, paired team-points MAE vs the
baseline's team points) is constructed as follows:

- **Statistic:** the mean paired difference, per market, over
  priced rows: candidate absolute error minus baseline
  absolute error, paired on the same row against the same
  final. Efficiency: one statistic for SPREAD rows and one for
  TOTAL rows; the leg passes only if **each** named market's
  interval clears (both markets are named in §5's leg; the
  screen read its leg the same per-market way). Team totals:
  one statistic over team rows.
- **Row set:** all priced rows of the family with a verified
  final (void and `RESULT_UNAVAILABLE` rows excluded per
  §1.4). Close validity is **not** a condition of this leg:
  §5's accuracy leg has no market input — it compares two
  models against finals — so a row with a missing or moved
  close still counts here. (This differs from NFL TT §6's
  single row set deliberately: NFL TT's accuracy legs are
  defined against the close line and Lane A's recorded means,
  so its row set is close-dependent; §5's is not.)
- **Construction:** game-cluster bootstrap — resample **games**
  with replacement (all of a game's rows of the family travel
  together; for team totals, a game's two team rows are one
  cluster), recompute the mean paired difference per resample,
  **10,000 resamples**, **seed 20261028** (the seed both
  packages bind — the only seed either family's record has
  ever bound, carried unchanged).
- **Level and bounds:** two-sided percentile interval at level
  **1 − α/k**, α = 0.05, with **k** the number of families
  validated or under active forward test in the program whose
  windows overlap this test's window, counting this family
  from its freeze date; k is computed at the freeze act and
  again at the verdict, and the larger k governs (at package
  time the packages computed **k = 12**, level 0.995833). The
  bounds are the ⌈q·B⌉-th order statistics of the B = 10,000
  resample statistics, q = (α/k)/2 and 1 − (α/k)/2
  (nearest-rank). "CI upper < 0" reads the upper bound,
  exactly as §5 states it.

*Provenance: adopted-from NFL TT §9 — game-cluster bootstrap,
10,000 resamples, seed fixed at freeze, two-sided at level
1 − α/k, larger k governs — with the k/seed values the CBB
packages themselves bind (k = 12 at package time, seed
20261028; NFL TT's own k = 11 and its seed are its family's
and are not imported). The per-market application and the
nearest-rank quantile rule are NEW narrow completions (NFL TT
§9 names neither for a two-market family); the close-
independent row set is adapted-from §5's own leg definition,
with the reason stated.*

## 3. G-3 — Close validity, moved rows, and missing closes

### 3.1 The close and its validity

- **Close:** the game's FINAL capture — the lines lane's final
  pre-tip write for the game under the standing two-mark
  cadence — supplying both sides of the row's market at one
  line, committed before tip.
- **A close is valid for a row only if all of the following
  hold**, checked in this order and **before** any moved
  classification (a row with no valid close is a capture
  failure, never a moved row): (i) the FINAL capture exists for
  the game; (ii) it is two-sided for the row's market (both
  prices present at one line); (iii) its capture timestamp is
  before tip and **no more than 60:00 before tip** (exactly
  60:00 is valid; a capture at or after tip is not a close);
  (iv) the pair is the final committed capture for the game at
  review time — "final" means final among records committed at
  review; later commits never rewrite a pairing.
- The 60:00 bound is hereby fixed as **this family's own
  rule**, adopted from the frozen form; it supersedes, for
  these families, the framework default `close_max_age_minutes`
  60 that the packages' draft configs carried expressly
  without preregistration force. The pairing-span and
  quote-freshness constants of NFL TT §7 are the NFL runner's
  declared constants and are **not** imported: a CBB close is a
  single captured body carrying both sides, so no intra-capture
  pairing span exists to limit.

*Provenance: adopted-from NFL TT §7 (close = last pre-kickoff
capture within 60:00; validity before moved classification;
final-among-committed rule), with the close identified as the
lane's FINAL write (§5's own "FINAL capture" language) and the
non-import of runner constants stated.*

### 3.2 Moved rows — the v1.1 bucket

A row whose close is valid but only at a line **different**
from the entry line is a **moved row** (`LINE_MOVED`). Moved
rows are excluded from the same-line CLV set (§1.3) and are
reported as a separate bucket, each with its direction: a
moved PICKED row is **FAVORABLE** if the closing line moved
toward the designated side (the market moved toward the
model: e.g. a PICKED OVER whose total line rose; a PICKED
HOME whose market-implied margin rose) and **ADVERSE** if it
moved away. The bucket is read **first**, in this order, as
in NFL props v1.1 (incorporated in NFL TT §6):

1. If the one-sided exact sign test of adverse vs favorable
   moved PICKED rows gives p < α/k in the adverse direction
   (α and k per §2; zero moved PICKED rows ⇒ the test is not
   run and this rule does not apply), the **market leg
   fails**, regardless of its point estimates.
2. Else, if more than 50% of PICKED rows are moved rows, the
   review's outcome is `INSUFFICIENT_CLOSE_DATA` (§3.3).

*Provenance: adopted-from NFL TT §6's moved-row rules (the
NFL props v1.1 bucket), with the consequence of rule 1 stated
as a market-leg failure — §5 has no NFL-style verdict label
set, and the moved-row evidence is part of the market leg's
own reading; the direction definition is NFL TT §6c's,
restated per CBB market.*

### 3.3 Missing closes and the insufficiency limit

Every priced row receives exactly one §3 disposition, counted
and reported, excluded from any mean it cannot enter, never
zero-filled: `NO_CLOSE_ROW` (no FINAL capture for the game),
`CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`,
`CLOSE_STALE` (last capture more than 60:00 before tip), or
`LINE_MOVED` (§3.2). Excluded-and-counted settlement codes
from §1.4 (`VOID`, `RESULT_UNAVAILABLE`, `PUSH`, `GAP_ZERO`)
complete the set. Any code not declared in the frozen package
(including this amendment, once adopted) that appears at
review is itself a defect and blocks the verdict
(`UNDECLARED_REFUSAL_CODE`).

**Insufficiency:** if more than **20%** of a family's priced
rows lack a valid close (the §3.1 failures
 — `NO_CLOSE_ROW`,
`CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE`;
moved rows hold a valid close and do not count against this
limit), the single review's recorded outcome is
**`INSUFFICIENT_CLOSE_DATA`** and no pass issues under this
preregistration; per §5's own rule there is no re-review
absent a new preregistration. The 20% figure is hereby fixed
as **this family's own rule**, adopted from the frozen form;
it supersedes, for these families, the framework default
`max_clv_missing_share` 0.2 that the draft configs carried
without preregistration force. The share is computed per
family across all its priced rows; the per-market shares are
reported alongside (reporting, not a second trigger).

*Provenance: adopted-from NFL TT §§6/8 — the 20%
insufficient-close limit, the one-code-per-row rule, the named
code set, and the UNDECLARED_REFUSAL_CODE defect rule — with
the two NFL runner-internal codes (`PAIR_SPAN_EXCEEDED`,
`QUOTE_STALE_180S`) not imported for the reason stated in
§3.1, and the outcome mapped to §5's single-review discipline
as stated.*

## 4. Review discipline — CBB cadence, stated (no new gates)

§5 fixes the verdict trigger, and this amendment adds **no**
numeric gate to it: **the verdict review happens once, at the
first slate close with ≥ 40 distinct graded games, both legs
read together; no re-review absent a new preregistration.**
What this section adds is the discipline around that trigger,
adapted from NFL TT §4 to CBB's daily cadence:

- **Slate:** one game date's captured board (the schedule
  substrate's game date). A slate is **full** when the T-1H
  (ENTRY) and FINAL writes ran for every population game on
  the date; a partial slate's valid rows still count toward
  the §5 gate — the §5 gate is games-based and names no slate
  minimum, so no slate gate is registered.
- **Why NFL TT §4's other minima are not imported.** NFL TT
  gates on ≥ 4 full slates, ≥ 150 priced rows with valid
  close pairing, and ≥ 50 picked rows, justified there by
  NFL's weekly supply (up to 32 team-total rows per slate, so
  its gates accumulate over ~5 slates). CBB's supply is of a
  different order: the pinned substrate carries **50 games on
  the first possible slate alone (Nov 2, 2026)** and full
  November dates carry dozens of games daily, so §5's
  40-distinct-graded-games gate can be met at the first or
  second slate close — long before any imported row, slate, or
  picked minimum could bind. Importing minima that bind
  *later* than §5's trigger would postpone the review past
  the point §5 names, which is altering a term, not completing
  one. They are therefore not imported, and this paragraph is
  the written justification the import would have required.
- **No interim looks** at the primary metrics before the
  review (operational monitoring — capture counts, refusal
  counts, missing-offer counts — is allowed and reports no
  accuracy, CLV, or ROI figures).
- **Missing-offer games** (population games with no DK offer
  in the family's market) are listed per slate in a
  `MISSING_OFFER` report with capture id and timestamp, never
  backfilled from another book, a later capture, or a derived
  split, and never counted in any denominator.

*Provenance: adapted-from NFL TT §4 — slate/full-slate
definitions, single review, no-interim-looks, and
missing-offer accounting carried; the numeric minima
deliberately not imported, with the CBB-supply justification
stated (NEW analysis, from the pinned substrate's counts the
packages record).*

## 5. Provenance index

| Added term | Where | Provenance |
|---|---|---|
| One amendment for both families | §0 | NEW (justified from the packages' inheritance language) |
| Gap definitions; designated side; `GAP_ZERO` | §1.1 | adapted-from / adopted-from NFL TT §5, §6c, §8 |
| Pick thresholds 2.2 / 3.5 / 2.1 (≈0.2σ̂) | §1.2 | adapted-from NFL TT §5 form; σ̂ derivation NEW from the screens' pooled MAEs |
| CLV definition; same-line matched pairs; de-vig | §1.3 | adopted-from NFL TT §7 |
| CLV read on the PICKED set; no picked-vs-passed condition; market leg on point estimates | §1.3 | NEW (narrowest reading of §5; non-imports stated) |
| Flat 1-unit stake; ROI = net ÷ picked count; push in denominator | §1.4 | NEW |
| Settlement, VOID, RESULT_UNAVAILABLE, push handling | §1.4 | adapted-from NFL TT §3 (CBB substrate) |
| Row record incl. baseline means at entry | §1.5 | adapted-from NFL TT §2 |
| Game-cluster bootstrap; 10,000 resamples; seed 20261028; level 1 − α/k; larger k governs | §2 | adopted-from NFL TT §9 (values per the CBB packages) |
| Per-market statistics; nearest-rank quantiles; close-independent accuracy row set | §2 | NEW narrow completions (reasons stated) |
| Close validity (60:00, two-sided, before tip, before moved classification) | §3.1 | adopted-from NFL TT §7 |
| Moved-row bucket; sign test at α/k; >50% moved rule | §3.2 | adopted-from NFL TT §6 (NFL props v1.1) |
| Refusal code set; one code per row; UNDECLARED_REFUSAL_CODE | §3.3 | adopted-from NFL TT §8 (two runner codes not imported, reason stated) |
| 20% insufficient-close limit → INSUFFICIENT_CLOSE_DATA | §3.3 | adopted-from NFL TT §6 |
| Slate/full-slate; single review; no interim looks; MISSING_OFFER | §4 | adapted-from NFL TT §4 |
| Non-import of NFL §4 numeric minima | §4 | NEW (justification from CBB supply) |

## 6. What does NOT change

Nothing in this amendment alters, restates with different
effect, or re-opens:

- any §5 term of either design as transcribed in the
  packages' PREREG_FINAL §1 — population, first possible slate
  (Nov 2, 2026), rows, the three data gates, both legs'
  criteria ("CI upper < 0"; "CLV > 0 and ROI > 0"), or the
  verdict rule (once, at ≥ 40 distinct graded games, both legs
  together, no re-review);
- the designs' §3 screen evidence or its dispositions —
  including, for the efficiency family, the criterion-2
  marginality disclosure (spread vs the simple baseline:
  −0.005 MAE, practically nil), which stands exactly as the
  screen report and the freeze package state it;
- the packages' recorded readings (R-1 forward input
  convention; A-1 moneyline scope — moneyline remains outside
  both tests; A-2 verdict unit) or their §6 discipline
  statements (k recomputed at act and verdict, larger governs;
  seed 20261028);
- the CBB first-half family, which is a separate family with
  its own design and no forward terms here;
- the freeze acts' other prerequisites: data gate (iii)
  (capture delivery proven on the opening slates) and finding
  F-1 (the forward-runner build) remain owed and are not
  supplied, waived, or narrowed by this amendment.

## 7. Verification — the amended legs are computable end to end (toy slate)

`verify_amendment2_toy_slate.py` (this directory; stdlib only;
sha256 `b7ddeb9d04c962dbc23851fab45fa7aa431c86bb4aa8d8996c2d2e92fc054646`)
executes §§1–3 exactly as written on a **toy slate of 12
invented games** — all teams, lines, prices, and results are
made up for this check — and writes
`amendment2_toy_slate_results.json` (sha256
`f915d91576b5c979ad1a3a79b6fb5aae5d5ea0c9044973f203507b13d5af133a`).
Every leg quantity the amendment defines was produced:

- **Efficiency:** 24 priced rows → 10 PICKED (incl. one PUSH,
  one moved-FAVORABLE, one moved-ADVERSE, one picked row with
  `NO_CLOSE_ROW`, one picked row with `CLOSE_STALE`); ROI
  = +0.4364 on the picked set; mean CLV = +0.0018 over the 6
  picked rows with valid same-line closes; missing-close share
  2/24 = 8.3% ⇒ not insufficient; moved bucket 1 adverse /
  1 favorable, exact sign test p = 0.75 ⇒ rule 1 not triggered;
  moved share of picked 2/10 ⇒ rule 2 not triggered; accuracy
  intervals at level 1 − 0.05/12 = 0.995833 — spread paired
  ΔMAE −0.225, CI [−1.733, +1.367]; total ΔMAE −1.583,
  CI [−2.792, +0.292].
- **Team totals:** 24 priced rows → 7 PICKED (incl. one PUSH,
  one moved-FAVORABLE); ROI = +0.2338; mean CLV = +0.0144 over
  6 same-line picked rows; missing-close share 1/24 = 4.2%
  (one `CLOSE_STALE`); sign test p = 1.0; accuracy ΔMAE
  −0.4625, CI [−1.496, +0.625].

The toy's accuracy intervals do not clear "CI upper < 0" —
expected on 12 invented games and irrelevant to the check:
the toy verifies **computability** of every amended leg
(pick classification, designated sides, CLV set arithmetic,
ROI with pushes in the denominator, close dispositions,
moved-row rules, insufficiency share, and the §2 interval at
its stated level/seed/quantile rule), not a verdict. The
§5 review gate (≥ 40 distinct graded games) is not met by a
12-game toy and no verdict is read from it.

## 8. Adoption and effect

Adoption is the owner's recorded act, in the manner of
Amendment 1: independent review closed on the exact head
carrying the adoption, the owner's authorization recorded,
and the adoption recorded by merge — never by this draft's
landing, a commit, or a review comment. On adoption, gaps
G-1, G-2, and G-3 in both packages' PREREG_FINAL §8 stand
supplied by this amendment (each PREREG_FINAL's pins are
unaffected — frozen text is never edited; amendments
supersede by reference, per the version rule both families
follow). Adoption alone still freezes nothing and counts
nothing: each family's freeze act remains a separate
prospective act on its own checklist, and each family's §6
machinery (evaluator/runner pins) is fixed at its own act.
If any term of this amendment is read to conflict with a §5
term as transcribed in the packages, §5 governs and the
conflict is itself recorded as a defect for the adoption's
review to resolve — this amendment completes §5; it does not
outrank it.

*Drafted Oct 28, 2026, from the two freeze packages of record
(PRs #2903 / #2904) and the program's frozen forms. DRAFT —
not adopted, not frozen; nothing counts.*
