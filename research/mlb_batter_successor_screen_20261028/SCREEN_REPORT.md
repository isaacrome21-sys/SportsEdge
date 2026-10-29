# SCREEN REPORT — MLB_BATTER_RATES_V1 (MLB batter successor)

**Verdict: FAILED_SCREEN — the construction is retired. No tuning follows.**

Executed Oct 28, 2026 (America/Chicago) in the single declared configuration
of `DESIGN.md` in this packet (written before any fitting, per the binding
conditions of the SmartStake admission, PR #2888). DESIGN/SCREEN ONLY: no
validation credit, no clock credit, no play eligibility. Market comparisons
are **"vs-close (timestamped, per book)"** — never verified CLV.
Attribution: SmartStake, CC BY 4.0.

## 1. What was run

- **Construction:** shrunk per-player rates (prior weight K = 20 toward the
  fit-window league mean) under a Poisson / negative-binomial count law
  (dispersion fitted per market on the fit window), expanding strictly-prior
  in-season features. No lineup, plate-appearance, matchup, park, or weather
  inputs exist in the admitted source; none were used. Market prices were
  never features.
- **Data:** SmartStake `mlb-player-props` @ `7cedfd3fe29f…`, all 18
  partitions re-verified against the admission manifest before use
  (**18/18 PIN_MATCH** — see `screen_results.json`). DraftKings rows
  scanned: **44,368,757**. Graded appearances (all windows): 89,716.
- **Split (preregistered):** fit 2026-03-21 → 2026-05-31 (μ, φ only);
  validation = graded June 2026 games (the source grades no July games;
  June is a partial month — 213 distinct games carried scored selections).
- **Evaluation units:** 13,471 main-line DraftKings-close selections with
  two-sided closes. Excluded and counted: 5,486 graded validation
  appearances with no two-sided DraftKings close (§3), 0 pushes.

## 2. Results by market (validation window)

ΔLL is mean log loss, model minus baseline; negative favors the model.
CIs are game-cluster bootstrap (2,000 reps, seed 20261028).

| Market | n | LL model | LL vs-close (DK) | LL simple | ΔLL vs market [95% CI] | ΔLL vs simple [95% CI] | Calib. diff | C1 | C2 | C3 | C4 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| player bases | 2,077 | 0.6769 | 0.6710 | 0.6839 | **+0.0059** [−0.0013, +0.0132] | −0.0070 [−0.0129, −0.0014] | −0.027 | ✓ | ✗ | ✓ | ✓ |
| player hits | 3,736 | 0.6731 | 0.6668 | 0.6786 | **+0.0063** [+0.0019, +0.0111] | −0.0055 [−0.0089, −0.0020] | −0.036 | ✓ | ✗ | ✓ | ✓ |
| player rbis | 3,724 | 0.6108 | 0.6059 | 0.6121 | **+0.0048** [+0.0004, +0.0094] | −0.0013 [−0.0055, +0.0029] | −0.005 | ✓ | ✗ | ✗ | ✓ |
| player home runs | 0 | — | — | — | — | — | — | ✗ | — | — | — |
| player strikeouts † | 295 | 0.7118 | 0.6915 | 0.7303 | +0.0202 [−0.0069, +0.0476] | −0.0185 [−0.0359, −0.0022] | −0.022 | ✗ | ✗ | ✓ | ✓ |
| player batting walks | 3,639 | 0.5898 | 0.5841 | 0.5998 | **+0.0057** [+0.0009, +0.0103] | −0.0100 [−0.0146, −0.0052] | +0.020 | ✓ | ✗ | ✓ | ✓ |

† Pitcher population at DraftKings (DESIGN §2). Brier scores move with log
loss in every judged market (model between simple rates and the close) —
full values in `screen_results.json`.

**Reading of the numbers:** player identity carries real signal — the model
beats league-only rates in four of five judged markets (all but RBIs) — and
calibration is inside the bound everywhere judged. But against the
DraftKings close the model loses in **every** judged market, significantly
so in hits, RBIs, and walks. The close embeds lineups, matchups, and
playing-time information this dataset does not contain, and shrunk raw
rates do not make that up. Per DESIGN §7, one judged market failing any
criterion is sufficient; four fail C2 and RBIs also fails C3.

## 3. The home-runs leg could not be judged — named, not hidden

DraftKings `player home runs` rows in the admitted source are
**over-only**: zero under rows in every partition checked (April and June
verified exhaustively; 444,875 over vs 0 under in June alone), so no
two-sided DraftKings close — and therefore no de-vigged market
probability — exists for the leg. All 3,746 graded June HR appearances
were excluded by the declared both-sides rule. (Other books do post HR
unders — 4.07M under rows across books in the June partitions — but the
design's close book is DraftKings; switching books after seeing the data
would be post-hoc, so it was not done.) The same rule, at smaller scale,
excluded ~1,660 bases selections whose lines never drew an under quote.
The strikeouts leg reached n = 295, five short of the C1 minimum of 300.

Under the declared verdict ordering these insufficiencies would have made
the screen NOT_EXECUTABLE on their own; the judged markets' C2 failures
precede them, so the verdict is FAILED_SCREEN.

## 4. Disposition

- `MLB_BATTER_RATES_V1` is **retired** as configured. No parameter of the
  declared design (shrinkage, dispersion, split, close book, criteria)
  was altered after the run, and no second configuration was tried.
- What this screen establishes, for the record: on the admitted 2026
  SmartStake data, per-appearance player rates beat league rates but do
  not beat the DraftKings close in any of the six admitted markets; the
  HR market has no two-sided DraftKings close in this source at all.
  Any future batter construction needs inputs the close already has
  (lineups / plate appearances / matchup) — a new design and a new
  preregistration, not a revival of this one.
- Fit-window constants, per-market detail, pins, and the full config are
  in `screen_results.json`; the runner is `run_screen.py`; helper tests
  are `tests/test_mlb_batter_rates_v1_screen.py` (15 passed).
