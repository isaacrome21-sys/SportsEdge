# DESIGN — CFB Team Totals V1 (`CFB_TEAM_TOTAL_POSSESSION_V1`)

- Status: `DESIGN_ONLY` — construction specified, screen not yet run,
  nothing frozen, no clock, no validation claim.
- Date drafted: 2026-10-27
- Family in scope: CFB team total points (`TEAM_TOTAL`) — one team's
  full-game points including OT, per DraftKings settlement. Two rows per
  game (home team, away team), each a two-sided OVER/UNDER at one line.
- Out of scope: game spread, game moneyline, game total (the retired /
  G3-gated sides-totals families), period team totals (covered by the
  period-lines design in this pack), player props.

## 0. Why this family, and why it is not a resurrection

The four retired CFB constructions (PM, AM, PRIOR_CURRENT_BLEND,
CFB_CONVERGED_ANCHOR_V1) all predicted the **game jointly** — a home/away
score pair, a margin, or a game total — by ridge regression or converged
ratings over blended team metrics, and all failed against the published
close (converged anchor, PR #2789 screen: spread β +0.037 < +0.10, MAE
12.92 vs close 12.12; total β +0.072, MAE 13.25 vs 12.52).

This construction differs in target, in functional form, and in the claim
being tested:

- **Target:** a *single team's* scoring distribution. The retired
  constructions never emitted a team-total prediction that was scored
  against a team-total baseline; their implied splits were by-products.
- **Form:** a multiplicative possession model (projected drives ×
  projected points per drive, §2), not a linear ridge over blended
  metrics and not an iterated ratings convergence. No coefficient,
  feature list, blending weight, or anchor from any retired construction
  is carried over. Early-season prior handling uses partial pooling
  toward the league mean (§2.3) — a generic shrinkage device, specified
  here with its own fixed constant — not the retired
  PRIOR_CURRENT_BLEND formula (which blended prior/current *team metrics*
  as inputs to a joint-score ridge; that is a different object, and it
  stays retired).
- **Claim:** the market prices a team total off two numbers (spread and
  game total) that are set jointly for the game. This construction prices
  each team's scoring from its *own* offensive/defensive matchup. The
  screen in the companion prereg draft tests precisely the disagreement
  between the model's split and the market's implied split — a claim the
  retired constructions never made and their screens never measured.

If the screen fails, this construction is recorded FAILED_SCREEN and
retired like the others. No retuning on the screen's seasons is permitted
(§5 of the prereg draft).

## 1. Question the construction must answer

Stated before any screen is run: on identical games, is a possession
model's team-points mean **more accurate than the market's implied team
total** (the split of the closing game total by the closing spread), and
does its disagreement with that implied split carry signal (positive
residual beta) — first on historical design seasons, and then, if the
screen passes and an owner freeze follows, against DraftKings' explicit
captured team-total lines on forward slates?

## 2. Construction

### 2.1 Form

For team *i* against opponent *j*:

```
projected_drives(i,j)  = pace blend of i's offensive tempo and j's
                         defensive tempo allowance (drives per game,
                         from plays and seconds-per-play)
points_per_drive(i,j)  = matchup of i's adjusted offensive finishing
                         profile vs j's adjusted defensive allowance
                         profile (see 2.2)
mean_points(i)         = projected_drives × points_per_drive
distribution(i)        = NegativeBinomial(mean_points, dispersion)
```

The dispersion parameter is fit on training folds only (never on an
evaluation season) and is a single pooled constant per evaluation fold,
recorded in the run record. `P(over line)` / `P(under line)` come from
the distribution with a continuity treatment at whole/half lines
(pushes graded per the prereg's settlement rules).

### 2.2 Inputs (all point-in-time, week-stamped)

Derived from **cfbfastR play-by-play** (sportsdataverse releases),
computed from raw PBP at screen/freeze build time — deliberately *not*
from retrospective ratings snapshots, whose own documentation warns some
rows are reconstructions rather than as-of-week values:

- offensive/defensive predicted points added (PPA) per play, split
  rush / dropback;
- success rate and explosiveness (offense and defense-allowed);
- Eckel rate and points per Eckel (finishing profile);
- drives per game, plays per drive, seconds per play (tempo);
- red-zone trip rate and red-zone TD rate (offense and allowed).

Context inputs: home / neutral site flag; game weather (CFBD game
weather: wind, temperature, precipitation) for outdoor games. All
features for a game are computed from games **strictly before that
game's week** in the same season, plus the §2.3 prior-season pool for
early weeks. Post-game facts only; walk-forward discipline throughout.

**Explicitly NOT used:**

- **No market line as a feature, at any stage.** The forecast function
  takes no spread, total, moneyline, or implied split as input. The
  market enters only as the baseline to beat.
- **No starting-QB identity.** Gap G3 (point-in-time pre-kickoff QB
  designations) is unresolved and is being audited separately; this
  construction does not cure it and does not use post-hoc recorded
  starters as a feature. The prereg's screen instead reports a flagged
  sensitivity stratum (games where the post-hoc recorded starter differs
  from the team's prior game) so the size of the unmodeled factor is
  measured, not hidden.
- No retrospective ratings (SP+, FPI, or any as-of-unverified snapshot).

### 2.3 Early-season priors

A team's rate stats enter with partial pooling toward the FBS league
mean: effective weight `w = n / (n + 3)` on the team's observed rate,
`1 − w` on the pooled prior (prior-season final rates carried at half
weight into the pool, league mean as the pool's center), where `n` is
the team's qualifying games this season. The constant 3 is fixed here,
before the screen, and is not swept. Eligibility mirrors the converged
screen's population discipline: a game is scoreable only from Week 5,
with ≥3 qualifying prior games for each team.

### 2.4 Settlement and identity

Final team points (including OT) from the SDV `cfb_schedules` release
(the converged screen's settlement source), joined on game_id — never
on team-name strings alone. Postponed / suspended-not-completed /
cancelled games are VOID per the prereg draft.

### 2.5 Illinois exclusion

Any game in which either team is an Illinois **college** team is
excluded before pricing or scoring: refused
`ILLINOIS_COLLEGE_EXCLUDED` via `sportsedge/registry_gate.py`
(`artifacts.free_models.IL_COLLEGE_NAMES`), excluded from every
denominator, and counted in an exclusion report. Illinois pro teams are
unaffected (there are no pro teams in this sport; the rule is stated so
the exclusion is never widened by accident).

## 3. Baselines the construction must beat

1. **Market baseline (governing).** Historical screen: the
   **close-implied team total** from the SDV published close —
   with home margin `S = home_score − away_score` convention,
   `implied_home = (T + S_close) / 2`, `implied_away = (T − S_close) / 2`
   where `T` is the closing game total. (The screen implementer must
   record the collector's spread sign convention from
   `scripts/collect_cfb_sdv_closes.py` at pin time and prove the identity
   on a sample of rows; if CFBD closes prove at pin time to carry
   explicit team-total fields, they are recorded and cross-checked
   against the implied construction — the implied baseline remains
   governing unless a prereg amendment says otherwise.) Forward test:
   DraftKings' explicit captured team-total close.
   SDV/CFBD closes are untimestamped → DESIGN baseline only; beating
   them is never "verified CLV."
2. **Existing-model baseline.** The incumbent CFB pricing path (the
   research-only game engine behind `CFB_RESEARCH_REGISTERED_FAMILIES`
   — moneyline/spread/total) implies a team total from its own emitted
   pair: `(projected_total ± projected_margin) / 2`. On the forward
   test, the incumbent's live emissions are captured per slate and
   pinned by hash, and the construction must beat its implied split on
   identical rows. The incumbent has no pinned historical emission, so
   on the historical screen this leg is represented by the naive
   baselines (leg 3) and the existing-model comparison is binding
   forward — this asymmetry is stated, not smoothed over.
3. **Naive baselines.** B1: team's own season-to-date mean points
   (walk-forward). B2: FBS league mean points per team-game
   (walk-forward). The construction must beat both on the screen's
   accuracy leg, as the NBA team-totals engine had to beat the baselines
   its historical screen beat.

## 4. Data sufficiency (why this family is buildable now)

- Outcomes + features: cfbfastR PBP and SDV schedules, 2014+
  (evaluation seasons 2023–2025; training may reach back to 2021).
- Market baseline: SDV published closes 2023–2025 (the converged
  screen's pinned source: 2,781 scoreable published-close rows) and
  CFBD betting lines 2013+ as a cross-check extract.
- Forward baseline: DK team totals are a standard CFB board offer;
  the lines lane must add explicit CFB TeamTotal lines to the CFB issue
  grammar (both teams, both sides, entry + close under the standing
  T-1H / FINAL cadence) — an arming precondition named in the prereg
  draft, not assumed done.

## 5. What this design does not do

- It does not freeze anything, start a clock, register the family, or
  change the registry gate. `team_total` stays BLOCKED at
  `sportsedge/registry_gate.py` until a separate governance act follows
  a screen pass.
- It does not price a single forward game. Pricing authority, if it
  ever exists, comes only from the companion prereg after a screen pass
  and an owner freeze.
- It does not touch sides/totals: a team-total verdict, pass or fail,
  says nothing about the retired constructions and reopens nothing
  gated on G3.
