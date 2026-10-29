# READINGS REGISTER — PGA H2H Leg 1 executor

Every place the design text or Amendment 1 leaves a constant, a form,
or a set definition unpinned, the executor either refuses without a
supplied value (UNPINNED parameters) or follows a named reading below.
**All of these are flagged for the adoption/freeze review** — the
review that adopts Amendment 1 and freezes the design must confirm or
replace each one on the record. None of them was tuned: each is the
most direct reading of the text, chosen before any result existed
(the executor has produced no results; its verdict path refuses).

## UNPINNED design parameters (no default; verdict path refuses)

| Parameter | Design text | State |
|---|---|---|
| `shrinkage_prior_rounds` | §4.1: skill "shrunk toward the field mean by rounds played" — no strength constant | UNPINNED — freeze act must pin |
| `cut_size` | §4.4: "per the simulated cut" — no size stated | UNPINNED — freeze act must pin (65-and-ties is the Tour's standard, but the design does not say it) |
| `day_draw_sd` | §4.3: "plus a shared course-day condition draw per round" — no magnitude | UNPINNED — freeze act must pin |
| `seed` | §4.4 fixes 100,000 sims but no seed | Run-record material; required explicitly at any verdict run |

Landing checks run with values labeled PLUMBING_ONLY (shrinkage 20.0,
cut 65, day-draw SD 0.35, 200 sims, seed 20261028). They are wiring
values, not design values, and appear under that label in every
record they touch.

## Named readings

- **R-OUT-1 (finish ordering).** `fin` parses to groups: numeric
  (T-prefixed included) < MDF < CUT < no-standing (WD/DQ/other).
  A pair is decided only when both sides hold a standing and their
  standings differ; equal standings are ties; pairs touching a
  no-standing row are undecided (excluded, counted). WD handling per
  design §5 is a Leg 2 / grading concern; for Leg 1 scoring this is
  the decided-finish rule Amendment 1 §3.2 step 4 assumes.
- **R-SKILL-1 (round dating).** A round's date is its event's date —
  the archive carries no per-round dates. The trailing-24-month
  window and the 6-month half-life act on event dates.
- **R-SKILL-2 (month length).** Age in months = days / 30.4375 (the
  mean calendar month). The 24-month cutoff uses calendar-month
  subtraction from the target date.
- **R-SKILL-3 (shrinkage form).** skill = (Σ w·sg + k·field_mean) /
  (Σ w + k), with w the §4.1 decay weights and k =
  `shrinkage_prior_rounds`; the field mean is the decay-weighted mean
  of all SG rounds in the same window. "Measured rounds" for the
  40-round floor are rounds with an SG value.
- **R-COURSE-1 (course fit form).** Adjustment = (n / (n + 8)) × mean
  SG over the player's rounds in prior editions of the same event
  (same `event_id`, strictly prior dates — the archive's only course
  proxy), n = those rounds; requires ≥ 2 prior editions, per §4.2's
  "no adjustment with <2 prior editions" and "prior weight equivalent
  to 8 rounds".
- **R-VAR-1 (residual SD).** Per-player SD of round **scores** around
  the player's own window mean score, population form (÷ n). §4.3
  says "residual round-score SD" without naming the centering; own-
  mean is the direct reading.
- **R-VAR-2 (field bounds population).** The 10th/90th percentile
  floor/cap is taken over players who are priceable at that target
  (≥ 40 measured rounds) with a computable SD; percentiles use linear
  interpolation.
- **R-SIM-1 (simulation space).** The simulation draws per-round
  performance in SG space: Normal(mu = skill + course_adj,
  sd = the player's §4.3 SD), plus the shared day draw. Finish order
  follows total performance; the score-residual SD stands in for the
  per-round performance SD (per-round score and SG deviations are the
  same quantity up to sign and the field's day component, which the
  shared draw carries separately). Non-survivors of the simulated cut
  rank below all survivors, ordered by R1+R2 performance; ties at the
  cut line survive.
- **R-REFA-1 (reference (a) pairs).** q_i = (1/close_i), normalized
  over the event's valid-close field; pairwise P(i ahead of j) =
  q_i / (q_i + q_j). A close is valid iff present, not the −9999
  sentinel, and > 1.0. Pairs where either side lacks a valid close
  are outside reference (a)'s scored set.
- **R-CAL-1 (calibration aggregation).** Criterion 3's "mean
  |predicted − realized| in probability deciles" = the unweighted
  mean over non-empty deciles of |mean predicted − mean realized|
  within the decile, over the candidate's scored pairs.
- **R-SET-1 (reference scored sets).** Criterion 1 and 2 compare
  pooled log loss over each reference's own priced set: the
  candidate's scored pairs restricted to pairs that reference can
  price. Amendment 1 §3.2 step 5 pins exactly this for (b′); the same
  form is applied to (a) by analogy. Flagged explicitly because the
  design's criterion sentence does not name the sets.
