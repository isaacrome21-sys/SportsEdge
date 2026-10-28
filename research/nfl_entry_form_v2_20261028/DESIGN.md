# DESIGN — NFL Sides & Totals Successor Construction V2

**Construction ID (proposed):** `NFL_ENTRY_FORM_V2` (short: EF_V2)
**Markets:** NFL spread (sides) and game total — two families, one
construction, gated separately.
**Status: DESIGN ONLY.** This document is not a preregistration, not a
freeze, not code that prices anything. Nothing in it prices a card, opens a
clock, starts a count, or changes any ruling. `NFL_ANCHORED_RATINGS_V1`
stays **FAILED-RETIRED** (closed Oct 27, 2026, PR #2809; independently
re-executed Oct 27, 2026, draft PR #2833 — failed again on the same
criteria). The Lane A `free_models.py` construction stays FAILED-RETIRED.
This is a new construction that must earn its own verdict on data its
design never touched. Freeze, if it ever happens, is Isaac's act, after
independent review closed on the exact head.
**Date:** Wed Oct 28, 2026 · **Author:** Rocky (Muse), under Isaac's
directives of Oct 27, 2026 ("Get verified engines. Everywhere."; "keep back
testing and fixing till we pass") and the gap-fill plan's build order item 3
(design the successor; formally admit the nflverse schedules closing
snapshot + QB/context fields as DESIGN data with named leak classes).
**Companion files (same directory):** `SCREEN_RESULTS.md` (design screens,
executed), `PREREG_DRAFT.md` (the preregistration draft this design
specifies), `design_screen.py` + `screen_results.json` (screen code and
machine output), `PINS.json` (input pins).

---

## 1. The failure record this design must answer

### 1.1 What failed, twice

`NFL_ANCHORED_RATINGS_V1` (NAR_V1): season-window SRS scoring-rate ratings
→ raw projection → **anchored issuance** `line + 0.15 · clamp(raw − line,
±4)` → normal probability map → picks at stated cover ≥ 0.545. Its frozen
pre-freeze screens, executed on 2020–2025 walk-forward (n = 1,517/market,
#2833 re-execution matching the original closure):

- **Screen 1 (beat the close):** anchored MAE 9.822 vs close 9.797 (spread);
  10.302 vs 10.298 (totals). FAIL both.
- **Screen 2 (calibration honesty):** spread band 2–3 overstates realized
  cover by +8.6 pp (> 7.5 allowed). FAIL.
- **Screen 3 (cover rises across disagreement bands):** spread realized
  cover 46.8 / 52.8 / 42.6 / 48.3% — not non-decreasing. FAIL. Totals FAIL.

### 1.2 The three defects, named

1. **No edge mechanism (Screen 1).** Anchoring guarantees the issued line
   is ≥ 85% the close itself; the remaining 15% tilt comes from a core
   whose raw MAE (10.704) is a full point worse than the close (9.797).
   Shrinking a worse forecaster toward a better one cannot beat the better
   one — the architecture has no place for an edge to live.
2. **Internal incoherence (the pick rule could never fire).** The design
   text (§3.1 of the retired design) computed the probability cap from the
   *pre-shrink* capped deviation, Φ(4.0/12.5) ≈ 62.6%. The implementation
   applied the map to the *post-shrink* anchored deviation, whose maximum
   is w·C = 0.15 × 4 = **0.6 pts**, capping stated cover at Φ(0.6/12.5) ≈
   **51.9% — below the construction's own 0.545 pick threshold**. Under
   that reading no pick could ever be emitted, even had the screens passed.
   Spec and implementation disagreed about which quantity enters the map,
   and nothing in the pipeline asserted fireability.
3. **No calibration gradient (Screen 3).** Realized cover did not rise
   across disagreement bands. This is the program-wide signature (retired
   design doc §1.3): for scores-based cores, disagreement with the close
   was the model's error, not its edge, and stated probabilities climbed
   while realized cover stayed flat.

### 1.3 What tonight's design screens add (summary; full record in `SCREEN_RESULTS.md`)

Because "try a different core" is the obvious first move, it was executed
before this design was written — three architecture families, all
walk-forward on the same design data, all against the closing snapshot:

- A **current-form EPA core** (the input class NAR_V1 explicitly deferred
  to "a V2": play-level EPA, season + last-4 form windows, QB EPA deltas,
  rest, pace, weather) is **worse than the close by ≈1.1 pts (margin) /
  ≈0.7–1.1 pts (totals)**, with flat band tables and −1.2% to −6.1%
  pick ROI. Form and context terms do not rescue it.
- A **close-residual context model** (fit the close's error from form/QB/
  rest/pace/weather only) improves nothing out-of-sample (adjusted MAE
  9.74–9.77 vs close 9.72 margin; worse for totals). The one hot cell
  (n = 11, +38.8% ROI) is a multiple-comparisons artifact and is flagged
  as such in the results file.
- The **QB-delta hypothesis is falsified**: in 295 QB-change games, the
  EPA-measured starter delta's sign covers 44.7%; correlation with the
  close's residual is 0.026. The close prices QB changes fine.
- A **dual-signal agreement gate** produces pooled figures (54.0% at
  |d| ≥ 5, margin) that dissolve under the band table: realized cover is
  non-monotone (46.5 / 57.4 / 55.6 / 45.9%) and stated probabilities
  overstate by up to +33.8 pp (margin) / +45.0 pp (totals).

**Conclusion the design is built on:** against the *closing* line, no
admitted input set produces an edge or a calibration gradient. Any honest
successor must therefore either (a) stop — record NO VIABLE CONSTRUCTION
on current inputs — or (b) make a claim the closing snapshot cannot
falsify because it is not a claim about the close. This design does (b),
narrowly, and §7 states the (a) alternative in full so the owner can
choose it with the same evidence in hand.

---

## 2. The edge mechanism (the claim, stated in two sentences)

**At the DraftKings entry snapshot (the lines lane's T-1H write), the
posted line has not finished incorporating the final pre-kickoff
information wave — official inactives and confirmed starters (~90 minutes
out), the personnel state the market prices last — while this
construction's projection is computed at that same moment from the
confirmed personnel state and current-form EPA, so its disagreements with
the *entry* line are claims about information timing, not about beating
the close. The claim is graded exactly where it lives: ROI at captured
entry prices and CLV against the captured close, under the v1.1 close
rule — if the close does not move toward the construction's disagreements
and entry prices do not pay, the construction is wrong and its kill
criteria close it.**

Why this is not already in the entry price, and why the design screens
cannot see it: every historical screen in this program (Lane A, NAR_V1,
tonight's) grades against a closing snapshot, by necessity — no admitted
historical source holds T-1H lines (gap G7: the nflverse snapshot is
sufficient for design screens; the counting baseline is DK forward
captures). The entry-timing claim is therefore **a hypothesis with no
design-data evidence for or against it**, and this design does not pretend
otherwise. What design data *did* establish shapes everything around the
claim: the core is not better than the close (§1.3), its probabilities are
uncalibrated against the close (§1.3), and its lone-disagreement picks are
its worst rows (the disagreement subset covers 47.3% where the two signals
conflict) — so the construction (i) never claims standalone superiority,
(ii) fires only where two independent signal paths agree, and (iii)
pre-registers calibration and CLV as forward verdict criteria with early
kills, instead of asserting them from history.

---

## 3. Defect-by-defect accounting

| # | NAR_V1 defect | EF_V2 fix | Proof / evidence |
|---|---|---|---|
| 1 | Anchored issuance: no place for an edge to live; core worse than close | No anchoring. The projection is never blended with any line. The benchmark for the edge claim is relocated from the close (unwinnable on all evidence) to the **entry line**, and the graded quantities are entry-price ROI + CLV — the quantities the forward program actually trades on | §2; screens in `SCREEN_RESULTS.md` establish the close-based claim is dead for every tested architecture, which is *why* the claim moved rather than being re-asserted with new inputs |
| 2 | Probability map consumed the post-shrink deviation (max 0.6 pts → stated ≤ 51.9% < 0.545 threshold); picks could never fire | The map consumes the **raw** deviation `d = projection − entry_line`; **no shrink, no cap** anywhere on the path from deviation to probability. σ is fitted on design residuals with the retired design's floor kept (σ ≥ 12.5) | **Fireability proof:** stated(d) = Φ(\|d\|/σ) ≥ 0.545 ⟺ \|d\| ≥ σ·Φ⁻¹(0.545) = 0.113σ. At the fitted design σ (margin 14.40, totals 13.95), the crossing is \|d\| ≥ **1.63 / 1.58 pts**; the pick rule additionally requires \|d\| ≥ 3.0, so every distance-gate pass clears the probability gate under the raw map (Φ(3/14.40) = 58.3% ≥ 54.5%). Pick supply is ample: on design data the agreement subset at \|d\| ≥ 3 is 388/1,119 games (35%). The freeze checklist (§6 of `PREREG_DRAFT.md`) adds a **unit test asserting stated(3.0) ≥ 0.545 and stated(5.0) ≥ 0.60 at the pinned σ** — the exact assertion whose absence hid NAR_V1's defect |
| 3 | Realized cover flat across disagreement bands; stated probabilities overstated by up to +40 pp (program-wide) | Calibration is **not claimed from design data at all** (the design band tables are printed in `SCREEN_RESULTS.md` as a disclosed negative). The prereg makes the forward band table a **pass/fail verdict criterion** — one-sided Cochran–Armitage trend p < 0.05 across five prespecified \|d_entry\| bands, no band (n ≥ 30) overstating by > 7.5 pp, top stated band realized ≥ 55% — and adds an **early calibration kill** (n ≥ 25 picks: top stated band n ≥ 15 realizing below break-even at prices taken → market killed) so a false calibration claim dies in weeks, not seasons | `SCREEN_RESULTS.md` §3 band tables (the negative evidence); `PREREG_DRAFT.md` §§4–5 (the forward criteria and kills) |

A fourth, quieter defect is also answered: NAR_V1's QB table was fitted on
design residuals and its away coefficients ran to the +4.0 cap — fitted
noise wearing a table's authority. EF_V2's screen program **tested the QB
term as a hypothesis and falsified it** (§1.3); the construction therefore
carries **no QB edge term**. QB/personnel state is an integrity input
only: the projection is computed from the confirmed starter state, and a
game whose starter state is unknown at pricing time is a PASS row, flagged
— never a pick.

---

## 4. Construction spec

### 4.1 Projection core (market-blind, current-form EPA)

Per team, from prior games only (strictly before kickoff, REG only), from
the pinned nflverse weekly team/player files (`PINS.json`):

- **EPA rates.** Offensive EPA/play = (passing EPA + rushing EPA) /
  (pass attempts + sacks suffered + carries) per team-week; defensive
  EPA/play allowed = opponent's offensive EPA/play in the same game.
  Season-window cumulative rates are shrunk toward 0 with a prior of
  **250 plays**; the prior season's final sums carry in at weight **0.30**.
- **Form blend.** Last-4-games rates, shrunk toward the season rate with a
  150-play prior; the core carries both a season term and a form-divergence
  term (form − season), so drift enters as its own fitted coefficient
  rather than a window replacement.
- **Score means.** Expected points for team *t* vs *u* =
  (off_t − def_u) × expected plays_t, with expected plays from the team's
  season pace average; league level is implicit (EPA is zero-centered).
  Home-field advantage is a single fitted constant. Margin and total come
  from the two score means — totals therefore have a real scoring-rate
  core (the retired totals construction's structural defect, answered by
  construction, as in NAR_V1's design).
- **Mapping to points.** One OLS fit per market on design data (2020–2025
  walk-forward residuals): margin ~ EPA margin + form divergence (the
  screen's spec B — the fullest spec whose coefficients were stable; the
  QB/rest terms are **excluded** from the projection because their screen
  ablations added nothing, C ≤ B in every table); total ~ EPA total + form
  divergence. Coefficients are fitted **once, at freeze, on design data**
  and pinned. **No refitting during validation** — a refit is a new
  version with its own preregistration.
- **Eligibility gate** (kept from the retired designs): both teams ≥ 3
  prior REG games in the current season window, else the game is refused,
  named, and counted.

### 4.2 Residual-agreement path (selection filter, not a projection)

A second, deliberately weak model — OLS on the market residual from the
context set (form divergence, QB EPA delta per side, rest differential
for margin; form divergence, pace deviation, wind, cold for totals),
fitted once at freeze on design data — exists in the construction **only
as a veto**. Its design-data performance is disclosed (it predicts nothing
against the close; `SCREEN_RESULTS.md` §2). Its role is the one thing the
screens did support: lone-signal disagreements are the worst rows
(disagreement subset cover 47.3%, ROI −7.9% on design data), so a pick
requires the two paths to **agree in sign**. The agreement gate is
specified as a noise filter with a disclosed design record — not as an
edge claim, and the prereg's verdict criteria do not credit it.

### 4.3 Selection (at the entry snapshot)

Computed once, at pricing time, from the lines lane's T-1H entry snapshot
and the runner's personnel context snapshot:

```
d        = projection − entry_line            (per market, signed)
adj      = residual_path(features at entry)   (signed)
p_raw    = Φ( |d| / σ_fit )                   (σ fitted on design residuals, floor 12.5)
PICK iff  sign(adj) == sign(d)
          AND |d| ≥ 3.0
          AND p_raw ≥ 0.545
          AND DK price on the picked side ≥ −165   (owner's straight-bet limit)
          AND both teams eligible (§4.1) AND both starter states known
Otherwise PASS: recorded, graded for accuracy/CLV diagnostics, never a pick.
```

Every captured game is priced; every rule-emitted pick counts; no
discretion, no slate-level selection. PAPER / 0u; rows display as LEAN
"unvalidated estimate", `verified_play = false`, until the preregistration
draft's verdict review passes in full.

### 4.4 What is deliberately NOT in this construction

- **No anchoring, shrinkage, or cap** between projection and probability
  (defect 2's mechanism, removed rather than re-tuned).
- **No QB edge term, no injury points, no referee term, no line-movement
  feature** — each is either falsified on design data (QB), unaudited
  (injuries, in the retired design's own words), or unmeasurable in the
  counting path (movement). A future version proposes its own term with
  its own evidence or it does not ship.
- **No moneyline market.** Sides and totals only, as in NAR_V1 (ML was the
  retired Lane A construction's worst cell).
- **No historical promotion path.** Nothing in §1.3's screens, however
  re-cut, can promote this family; the verdict is forward-only
  (`PREREG_DRAFT.md`).

---

## 5. Why this is not a resurrection of NFL_ANCHORED_RATINGS_V1

| Dimension | NAR_V1 (FAILED-RETIRED) | EF_V2 (this design) |
|---|---|---|
| Core inputs | Scores only (SRS points ratings); EPA/PBP explicitly excluded | Play-level EPA (season + form windows); scores enter only via EPA aggregation |
| Use of the line | **Inside the output**: issued line = close blended with projection (w = 0.15, cap 4) | **Benchmark only**: the projection never touches a line; the entry line appears only in `d` and in grading |
| Edge claim | Beat the close's MAE with an anchored line (falsified twice) | Entry-timing: ROI at entry prices + CLV vs close (untestable on design data; forward-only) |
| Probability map input | Post-shrink deviation (max 0.6 pts) — could not reach its own threshold | Raw deviation, uncapped; fireability proven in §3 and unit-tested at freeze |
| QB term | Fitted 4-class table, \|δ\| ≤ 4, carried as signal | **No QB edge term** — the hypothesis was screened and falsified; personnel state is integrity/refusal only |
| Calibration stance | Compression fitted on design band table pre-freeze | No design calibration claimed (band tables disclosed as negative); calibration is a forward verdict criterion + early kill |
| Selection | Anchored deviation ≥ 1.0 pt + p_cal ≥ 0.545 | Dual-signal agreement + \|d\| ≥ 3.0 + p_raw ≥ 0.545 + price/eligibility/personnel gates |

Shared elements are governance, not construction: the eligibility gate,
the −165 price cap, the v1.1 close rule, the kill-criteria pattern, and
the one-review anti-peeking rule are program law carried by reference —
the same machinery every family in this program runs under.

---

## 6. Relationship to surviving NFL families (non-interference)

- **NFL props Part 2 / 2B** (frozen, sha256-pinned pricers/evaluators):
  untouched. Different markets and clocks; the only shared machinery is
  the shared forward evaluator and the v1.1 close rule, used read-only by
  reference and pin.
- **ATD v1.1** (frozen @ c2fd86dc): untouched. Its landing-check lesson is
  adopted (the prereg requires a verified records path before its first
  counted slate).
- **Passing-yards v2 screen** (opens Oct 29–Nov 2, 2026): untouched and
  ungated by this design. If it validates, k in the multiple-testing
  divisor grows; noted, not negotiated.
- **Lane A `free_models.py`**: stays in place, FAILED-RETIRED, unedited.
  Its role here is exactly one: the **existing-model baseline** the
  preregistration's validation must also beat (per the Oct 27, 2026
  verified definition — passage requires beating BOTH the existing model
  and the market baseline).

---

## 7. Honest readiness verdict

**DESIGN ONLY — preregistration drafted; freeze NOT recommended on design
evidence, and the alternative verdict is stated plainly.**

For freezing: the construction is fully specified (every procedure and
constant in `PREREG_DRAFT.md` §6 either carries a number or a fit-once
procedure); its one untestable-on-history claim is the kind this program
exists to test forward (ATD v1.1's calibration leg was likewise a forward
claim); its kill criteria fire within the first month of picks if the
claim is false; and its pick supply (≈35% of games at design parameters)
fills the validation sample inside the 2026 remainder + a short extension.

Against freezing: every close-based screen failed, for this input set and
for two retired ones; the entry-timing hypothesis may simply be the last
untested place for a nonexistent edge to hide; and a freeze spends the
program's scarcest asset — a clean forward clock — on a hypothesis with
zero positive evidence behind it, only un-falsified space. **If the
owner's standard is "screens pass first," the correct record for this
family on current inputs is NO VIABLE CONSTRUCTION, and this design's
screens are the evidence for that record.** The design is delivered with a
preregistration draft because the owner's directive is to keep testing
until constructions pass, and the only test this claim can pass or fail is
the forward one — specified here tightly enough that its failure, if it
fails, is fast, cheap, and unambiguous.

**Recommended next step (owner's call):** independent review of this
design + prereg draft on their exact heads; if the owner elects the
forward test, build the construction module + evaluator adapter, fit the
§4 constants on design data, pin everything per the freeze checklist, and
run the landing check on a non-counted slate before the first counted
one. If the owner elects NO VIABLE CONSTRUCTION, record it against this
directory and stop the NFL sides/totals line until a genuinely new input
class (e.g. an admitted timestamped entry-line archive) exists.
