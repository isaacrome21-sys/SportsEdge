# DESIGN + PREREGISTRATION DRAFT — CFB Quarters / Halves V1 (`CFB_PERIOD_SCORING_V1`)

# DRAFT — NOT FROZEN. NO CLOCK RUNS UNDER THIS DOCUMENT.

- Status: `DESIGN_ONLY` — construction specified; market validation
  is **forward-only** (no historical period lines exist in any
  admitted source); nothing frozen.
- Date drafted: 2026-10-27
- Family in scope: CFB period lines — first-quarter spread and total
  (`Q1_SPREAD`, `Q1_TOTAL`), first-half spread and total (`H1_SPREAD`,
  `H1_TOTAL`), and first-half team totals (`H1_TEAM_TOTAL`) where DK
  posts them. Second-half lines are **out of scope** for V1: they are
  priced in-play-adjacent (posted at halftime against a known state),
  and belong to the live pilot's problem set, not this pregame family.
- Engine under test: `CFB_PERIOD_SCORING_V1` (specified in §2).

## 0. Up-front honesty

There is **no historical market baseline for this family, at all.**
No admitted source carries historical CFB quarter/half lines (the
same absence the gap plan records for prop history, G1, applied to
periods). Two consequences, stated rather than smoothed over:

1. The historical work possible today is an **accuracy/calibration
   diagnostic** against play-by-play period scoring and naive share
   baselines (§4). It can kill a bad construction; it cannot validate
   one against a market.
2. The family's market verdict exists only in the forward test (§5),
   against DraftKings' captured period closes. Any freeze request
   therefore comes **after** capture has proven out on real slates —
   the reverse order from team totals, and deliberately so.

## 1. Question

Do teams have persistent, point-in-time-measurable **period scoring
traits** (first-quarter scoring rate, first-half share of game points,
early defensive allowance) that deviate from the league-average period
shares the market uses to derive period lines from full-game lines —
enough that a trait-based period mean beats the captured DK period
close on accuracy and earns positive CLV on picked rows?

## 2. Construction

Period lines at DK are derivatives: books set them from the full-game
line via near-league-average period shares. The construction prices
periods directly:

```
period_mean(i, P) = full_game_scoring_rate(i) × period_share(i, P)
                    adjusted for opponent period allowance traits
```

- `period_share(i, P)`: team i's walk-forward share of its points
  scored in period P (Q1; H1), and the mirror defensive shares for
  the opponent, computed from cfbfastR play-by-play period scoring,
  games strictly before the current week, with the same partial
  pooling discipline as the team-totals design (prior constant 3,
  Week-5 eligibility, ≥3 prior games).
- `full_game_scoring_rate(i)`: the team's walk-forward points per
  game (own mean and opponent-allowance blend). This is a scoring-rate
  input to a *period-share* model — it is not the retired joint-score
  constructions, and no margin/total prediction is emitted or scored
  under this document.
- Distribution: period points modeled as Negative Binomial around
  the period mean (dispersion fit on training folds only), giving
  P(over/under) at period totals and cover probabilities for period
  spreads from the two teams' period distributions.
- **No market input** to any forecast function. **No QB-identity
  input** (G3 unresolved; same flagged-stratum reporting duty as
  team totals if the family reaches a screen).
- Illinois exclusion: identical mechanism and refusal code as the
  team-totals design (`ILLINOIS_COLLEGE_EXCLUDED`, applied first).

## 3. Data

- Features/outcomes: cfbfastR play-by-play (period scoring derivable
  per drive/play), SDV schedules for identity/settlement of period
  finals (period scores cross-checked against PBP; a game whose two
  sources disagree on a period final is `RESULT_UNAVAILABLE` for the
  affected period arm — counted, never resolved by hand).
- Forward lines: DK captured period lines. **Arming precondition:**
  the lines lane must carry priced 1Q/1H lines (not only comment
  material) in CFB issue bodies under the standing cadence, and the
  intake grammar must accept them; until a capture audit proves that
  on real slates, no slate counts toward any gate.

## 4. Historical diagnostic (not a screen; cannot pass the family)

On 2023–2025 design seasons, Week 5+ FBS vs FBS, identical-rows:
period-mean MAE and 80%-interval coverage vs (a) league-share
baseline (full-game actual total × league period share — a
hindsight-armed straw baseline, labeled as such), (b) walk-forward
league-share forecast (team scoring rate × league share), (c) team
naive period mean. **Kill rule (fixed here):** if the construction's
period-mean MAE does not beat baseline (b) on both Q1-total and
H1-total arms in the pooled diagnostic, the construction is recorded
FAILED_DIAGNOSTIC and retired before any freeze request. Passing the
diagnostic earns only the right to request a freeze after §3's
capture precondition is met.

## 5. Forward test (proposed terms; bind only on a future owner freeze)

Modeled on the team-totals prereg in this pack, with period-specific
terms:

- Markets: the §-header list, each arm scored separately; the family
  verdict requires the pooled test across arms plus no single arm
  failing its accuracy leg by the moved/adverse rules.
- Entry = first ENTRY capture at the main period line; close = last
  capture before kickoff (for Q1/H1 lines the close is the pregame
  close; halftime-posted lines are never entries or closes here).
- Pick rule: `gap = period_mean − entry_line`; PICKED if
  `|gap| ≥ 1.5` points for totals arms and H1 spread, `≥ 1.0` for Q1
  spread (period scale; stated here, before data, and changeable
  only by new version).
- Gates (minimums): ≥4 full slates, ≥40 distinct games, ≥150 priced
  rows, ≥50 picked rows, **and ≥30 priced rows in each arm** (a
  family verdict may not ride on one arm's volume). Single verdict
  review at the first slate close where all gates are met;
  anti-peeking as in the team-totals draft.
- Primary legs: 7a ΔMAE vs DK period close (CI upper < 0), 7b vs
  naive/share baselines and the incumbent's implied period split
  (full-game incumbent emission × league shares — the market's own
  derivation method, priced by the incumbent), 7c CLV, 7d hit −
  p_close; moved-row rules and the >20% insufficient-close rule
  identical to the team-totals draft; intervals game-cluster
  bootstrap 10,000 at 1 − α/k, α = 0.05, k recorded at freeze/review.
- Settlement: period finals from official box/PBP per §3.
- Verdicts: `BEATS_MARKET` / `DOES_NOT_BEAT_MARKET` /
  `INSUFFICIENT_CLOSE_DATA`, with the same effect language as the
  team-totals draft (validation evidence only; registration changes
  are owner rulings).

## 6. What this design does not do

No freeze, no clock, no registration change (period families are not
in `CFB_RESEARCH_REGISTERED_FAMILIES`), no forward pricing. The
diagnostic in §4 is the only computation this document authorizes,
and it is labeled DIAGNOSTIC wherever its numbers appear.
