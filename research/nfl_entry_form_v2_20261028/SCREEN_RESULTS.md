# DESIGN SCREEN RESULTS — NFL_ENTRY_FORM_V2 candidate inputs

**Evidence state: DESIGN ONLY.** Every number below comes from 2020–2025
historical data — data already seen by the retired `free_models.py` Lane A
construction, by `NFL_ANCHORED_RATINGS_V1` (closed FAILED_SCREEN, PR #2809),
and by the Oct 27, 2026 re-execution (draft PR #2833). Per standing law this
data is DESIGN data for this family: these screens can kill a mechanism or
shape a design; they are **zero validation credit**, support no verified
claim, open no clock, and count no rows. The market baseline is the nflverse
closing snapshot — **vs-close, never verified CLV**. 2026 rows were never
loaded into any fit or feature: the 2026 remainder is reserved untouched for
the preregistration draft's validation split.

**Method (one paragraph).** Walk-forward by season: for each test season
2021–2025, all coefficients were fitted on seasons strictly earlier, and
every team/QB feature for a game uses games strictly before that game.
Eligible games: REG, both teams ≥ 3 prior in-season REG games (the retired
design's gate, kept). Eligible feature rows 1,327; walk-forward test rows
n = 1,119. Inputs and sha256 pins: `PINS.json` (games file = the PR #2831
pin; weekly team/player parquets pinned per file). Code: `design_screen.py`
beside this file; full machine output: `screen_results.json`.

**Sign-convention note (a caught error, recorded per the self-audit rule).**
An early prototype read `spread_line` negated and produced impossible
results (a model "beating" the close by 3.7 pts with +57% ROI). The error
was caught by reconciling against the program's known close MAE: nflverse
`spread_line` **is** the market's home-margin estimate — MAE(margin vs
+spread_line) = 9.764 on all 1,615 priced 2020–2025 REG games (the
walk-forward test subset gives 9.720), the negated reading gives 14.26. The
invalid run was discarded in full; only corrected-convention numbers appear
here. This matches the #2833 re-execution's empirically-derived convention
(their close MAE 9.797 on their n = 1,517 subset; subset differences account
for the small delta).

---

## Screen 1 — standalone current-form EPA core vs the close

The strongest standalone core buildable from the admitted inputs:
opponent-adjusted off/def EPA/play (season window, shrunk, prior-season
carry), a last-4-games form blend, expected points via team pace, fitted
walk-forward by OLS. Ablations: **A** season EPA only · **B** A + form
divergence · **C** B + QB EPA delta + rest (margin) / pace + weather (totals).

| Spec | MAE model | MAE close | Pick cover* | Pick ROI (flat −110) | Band trend p |
|---|---|---|---|---|---|
| Margin A | 10.832 | 9.720 | 49.2% (n=841) | **−4.1%** | 0.362 |
| Margin B | 10.851 | 9.720 | 49.3% (n=835) | −3.8% | 0.617 |
| Margin C | 10.871 | 9.720 | 48.2% (n=826) | −6.1% | 0.229 |
| Total A | 10.962 | 10.254 | 49.8% (n=759) | −4.0% | 0.101 |
| Total B | 11.062 | 10.254 | 50.3% (n=781) | −3.1% | 0.412 |
| Total C | 11.382 | 10.254 | 51.2% (n=789) | −1.2% | 0.193 |

\* Picks = |model − close| ≥ 2 and Φ(|d|/σ_fit) ≥ 0.545 — the fireability
gate, included to prove the selection rule produces a full slate of picks
(74–84% of games clear |d| ≥ 2). It does not produce an edge.

Realized cover by |d| band is flat for every spec (e.g. Margin A:
53.7 / 50.0 / 43.8 / 48.1 / 52.4% across 0–1 / 1–2 / 2–3.5 / 3.5–5 / 5+).
**Verdict: the standalone EPA core is ≈1.1 pts (margin) and ≈0.7–1.1 pts
(totals) WORSE than the close as a point forecast, and its disagreement with
the close carries no calibration gradient. As a claim to beat the close, it
fails — the same signature as the retired constructions.** Fitted σ:
margin ≈ 14.4, totals ≈ 13.9 (walk-forward train means).

## Screen 2 — close-residual context model vs the close

Base forecast = the close itself; OLS fits only the close's residual from
the predeclared context set. Ablations: **A** form divergence · **B** A + QB
delta (margin) / pace deviation (totals) · **C** B + rest (margin) / wind +
cold (totals).

| Spec | MAE adj. | MAE close | Share \|adj\| ≥ 2 | Band trend p |
|---|---|---|---|---|
| Margin A | 9.736 | 9.720 | 1.0% | 0.140 |
| Margin B | 9.769 | 9.720 | 6.8% | 0.355 |
| Margin C | 9.774 | 9.720 | 7.1% | 0.463 |
| Total A | 10.350 | 10.254 | 10.1% | 0.960 |
| Total B | 10.412 | 10.254 | 18.1% | 0.679 |
| Total C | 10.487 | 10.254 | 21.9% | 0.759 |

No spec improves on the close out-of-sample; the context features carry no
usable residual signal against the closing line. Two cells demand explicit
warnings because they are exactly what a tuning pass would seize on:

- **Margin A, |adj| ≥ 2: cover 72.7%, ROI +38.8% — on n = 11.** At
  |adj| ≥ 1.5 the same spec is 52.0% (n = 50, ROI +3.4%), and adding the QB
  or rest terms reverses it (47.6%, ROI −6.9%). A 11-game cell inside a
  multi-spec screen is a multiple-comparisons artifact, **not a finding**,
  and it is recorded here so nobody cites it as one.
- **Totals A (form only) ANTI-predicts:** picks cover 41.6%, ROI −19.9%;
  realized cover *falls* as |adj| grows (trend p = 0.960 for an increase).
  Recent-form scoring divergence in totals is information the close has
  already more than absorbed on this data.

## Screen 3 — targeted probes

**QB-change games (the "close prices QB changes with a coarse generic step"
hypothesis).** n = 295 games where a recorded starter differed from his
team's previous game. Cover when following the sign of the EPA-measured
starter delta: **44.7%** overall; at |QB delta| ≥ 2 pts: **45.1% (n = 164),
flat-110 ROI −12.8%**; correlation between the QB delta and the close's
residual: **0.026**. **The hypothesis is falsified on design data.** The
close prices recorded QB changes at least as well as an EPA delta does.
(Recorded starters are post-hoc identity with the plan's named leak class —
game-time scratches; the falsification is therefore conservative: even with
that leak in its favor, the delta shows nothing.) Consequence for the
design: QB state remains a *projection-integrity* input (a projection must
know who is starting) and a *refusal* condition when unknown — but the
construction claims **no edge** for it.

**Dual-signal agreement gate.** Picks require the standalone core's
deviation and the residual model's adjustment to agree in sign (each model
vetoes the other's lone disagreements):

| Subset | n | Cover | ROI (flat −110) |
|---|---|---|---|
| Margin agree, \|d\| ≥ 3 | 388 | 51.5% | +1.0% |
| Margin agree, \|d\| ≥ 5 | 261 | 54.0% | +6.8% |
| Margin disagree, \|d\| ≥ 3 | 315 | 47.3% | −7.9% |
| Total agree, \|d\| ≥ 3 | 321 | 50.5% | −2.7% |
| Total agree, \|d\| ≥ 5 | 194 | 48.5% | −7.0% |

The margin pooled figures look mild-positive until the band table is read —
which is the retired design's Screen-3 lesson, so it is printed in full:

Margin, agreement subset, stated Φ(|d|/σ) vs realized cover:

| \|d\| band | n | Stated | Realized | Overstatement |
|---|---|---|---|---|
| 3–5 | 127 | 60.8% | 46.5% | **+14.4 pp** |
| 5–7 | 101 | 66.1% | 57.4% | +8.7 pp |
| 7–10 | 99 | 71.8% | 55.6% | +16.2 pp |
| 10+ | 61 | 79.7% | 45.9% | **+33.8 pp** |

Cochran–Armitage trend p = **0.369** (not monotone; the largest disagreements
are the model's worst errors — the §1.3 signature of the retired design's
failure analysis, reproduced with new inputs). Totals agreement bands are
worse (top band realized 35.1% vs stated 80.2%, +45.0 pp overstatement,
trend p = 0.808).

**Verdict: against the CLOSE, the agreement gate does not produce
calibration either.** The pooled 54.0% at |d| ≥ 5 is averaging across a
non-monotone band table on seen data and earns no claim.

---

## What these screens do and do not establish

**Established (design-stage facts):**

1. No input set admitted for this family — scores (retired designs), EPA
   season/form, QB EPA delta, rest, pace, weather, or any dual-signal
   combination screened tonight — produces a projection or adjustment that
   beats, or calibrates against, the **closing** line on 2020–2025.
2. The pick-rule fireability defect of the retired design is an
   architecture defect, not a data fact: with the probability map on the
   **raw** deviation and fitted σ ≈ 14.4, the 0.545 threshold is crossed at
   |d| ≥ 0.113σ ≈ **1.63 pts**, and 74–84% of games clear |d| ≥ 2. A
   correctly-built map fires; the retired map (post-shrink deviation
   capped at w·C = 0.6 pts → max stated Φ(0.6/12.5) ≈ 51.9% < 0.545) could
   not. See `DESIGN.md` §3.
3. Every stated probability from a raw-deviation normal map overstates
   realized cover, increasingly with |d| (up to +45 pp). Any future
   construction in this family must treat its probabilities as uncalibrated
   until a forward band table demonstrates otherwise.

**Not established — the one claim design data cannot test:** all screens
above grade against the closing snapshot, the most efficient number the
market publishes. SportsEdge does not price at the close; it prices at the
DraftKings **entry** snapshot (T-1H lane write) and grades ROI at entry
prices and CLV against the close. Whether a current-form projection's
disagreements with the **entry** line earn positive CLV and ROI is a claim
about information timing between T-1H and kickoff. No admitted historical
source contains T-1H snapshots, so no design screen can measure it — it is
testable only forward, which is what `PREREG_DRAFT.md` specifies, with kill
criteria that fire early if the answer is no.
