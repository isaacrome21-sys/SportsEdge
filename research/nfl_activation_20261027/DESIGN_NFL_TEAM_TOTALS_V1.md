# DESIGN — NFL team totals: `NFL_TEAM_TOTAL_DIST_V1`

**Status: DESIGN, with preregistration draft. Family state on landing:
ARMED pending owner freeze** (freeze checklist in the prereg draft).
Family before this pack: NO_CONSTRUCTION (priced on research cards
only; no prereg, no clock). PAPER / research only.

## 1. The market and why it might be wrong

DraftKings posts a team total for each team in every NFL game — a
two-sided over/under on that team's points. The line is anchored to
the game's closing structure: the traded total and spread imply a
split, and the team-total market trades around it. That anchor is
also the opportunity. A team's scoring *distribution* is not
determined by its implied mean: two teams with the same implied 24.5
differ in touchdown/field-goal mix, red-zone efficiency, pace, and
fourth-down aggression, and those traits shape the tails the over/under
price actually trades on. The closing spread and total encode the
market's view of the *game*; the team-total line inherits that view by
decomposition. A construction that models each team's points directly
— from that team's own point-in-time scoring and its opponent's
point-in-time allowance, never from the market — can disagree with the
decomposition for identifiable reasons, and the disagreement is
testable: the forward preregistration makes the DK closing team-total
line the governing baseline, so if the decomposition is in fact as
good as direct modeling, this family records DOES_NOT_BEAT_MARKET and
stops. (The design screen's implied-split diagnostic, `SCREEN_REPORT.md`,
says the market leg is the hard leg. That is disclosed, not hidden.)

What this construction is **not**: it is not the retired
NFL_ANCHORED_RATINGS_V1 (a market-anchored ratings blend that failed
its screen and stays retired). This construction takes **no market
input at all** — no spread, no total, no line enters any feature. The
market appears only as the thing to beat.

## 2. The construction (as screened)

For team T vs opponent O in week w of season s, using only games
completed before the game (regular season):

- **Sample:** T's same-season prior games, supplemented by T's most
  recent prior-season games until the sample reaches 8 games (or
  history exhausts). Same for O's points-allowed sample.
- **League pool mean G:** mean team score over strictly earlier weeks
  of the season; the previous season's full league mean in week 1
  (the Part 2 league-pool form).
- **Shrunk rates (K = 3, the Part 2 shrinkage constant, adopted
  because this family's per-team sample sizes and the shrinkage
  problem are the same shape as Part 2's player samples):**
  off_T = (Σ T's sample scores + 3·G) / (n + 3);
  def_O = (Σ O's sample points allowed + 3·G) / (n + 3).
- **Mean:** μ_T = off_T · def_O / G (multiplicative opponent
  adjustment: T's scoring rate scaled by how much O's defense concedes
  relative to an average defense).
- **Distribution:** Negative Binomial with mean μ_T and variance
  (c·μ_T)², Poisson where variance ≤ μ; c is the pooled coefficient of
  variation of (score / μ) over the **2018–2019 training seasons
  only** (c = 0.4644 in the design screen). c is a training constant,
  re-derived only under a new version.
- **Outputs:** the full distribution over team points (0–120), hence
  P(over)/P(under) for any posted line, the mean μ_T, and the B1/B2
  reference means (B1: T's unshrunk sample mean; B2: G) emitted with
  every priced row for the validation's baseline legs — exactly as the
  NBA team-totals preregistration emits its baselines.

**Point-in-time rules:** features for a game use only games final
before that game's entry capture; the history snapshot for each slate
is hashed before pricing and a failed refresh fails the slate closed
(the NBA team-totals §11 discipline, adopted). Recorded starting-QB
identity from the nflverse schedules snapshot is *not* a feature of
v1 — the schedules baseline carries it and the gap plan names its
leak class (post-hoc identity); v1 deliberately prices without it
rather than inherit the leak.

## 3. Design screen (entry ticket — summary)

Walk-forward on the 2020–2025 design seasons (all seen data), full
numbers in `SCREEN_REPORT.md`: **PASS** against the pre-committed
criteria — pooled MAE 7.749 vs B1 7.831 / B2 7.924; pooled CRPS 5.528
vs 5.590 / 5.625; no season breached the guard. Calibration: PIT mean
0.537, 91.0% inside the central 90% band. And the disclosure that
travels with the pass wherever it is cited: the candidate **loses to
the implied split of the closing snapshot (MAE 7.250)**. The screen
asked whether direct team modeling beats naive team/league means. It
does, narrowly. Whether it beats DraftKings is the forward test's
question, and the prior from this diagnostic is that it will be close
at best.

## 4. Inputs (all admitted/pinned or forward captures)

- **nflverse schedules + results** (nflverse-data releases): the
  design baseline pinned in draft PR #2831 (`games.csv.gz`, with the
  rolling-asset drift discipline of the hoopR substrate admission:
  each pull is hash-recorded; drift surfaces as a changed hash, never
  a silent substitution). Scores are post-game facts — leak-free
  under walk-forward.
- **Forward DraftKings captures** (the lines lane): `TeamTotal` lines
  are already priced body lines in the NFL intake grammar
  (`sportsedge/nfl_lines_intake.py`), inside Capture Spec V1's scope,
  at the standing T-1H + FINAL cadence with the five #2792 receipts.
  **No capture expansion is required for this family** — the only one
  of the five for which that is true.
- Lane A (`artifacts/free_models.py`) prices TEAM_TOTALS today from
  its own means; it is the existing-model baseline of the validation,
  hash-pinned at the family's freeze, and is never an input.

## 5. What stands between this design and a running clock

1. Engine build of §2 as a committed module with the Part 2 hash-pin
   discipline (the pricing runner refuses rows if the engine on disk
   does not match the freeze pin), independently reviewed.
2. Owner freeze of the prereg draft (the freeze names the first
   counted slate: the first slate priced after the pin).
3. Nothing else: capture exists, baselines exist, the screen passed.
   That is what ARMED pending owner freeze means here — and the
   freeze remains the owner's act, not a formality this pack performs.
