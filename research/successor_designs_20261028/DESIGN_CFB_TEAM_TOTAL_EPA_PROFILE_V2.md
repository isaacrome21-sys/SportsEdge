# DESIGN — CFB Team Totals Successor: `CFB_TEAM_TOTAL_EPA_PROFILE_V2`

**Status: DESIGN — NOT BUILT, NOT FROZEN.** This document specifies a
construction and the screen it must pass. Nothing in it prices a game,
opens a clock, starts a count, registers a family, or changes the
registry gate. `CFB_TEAM_TOTAL_POSSESSION_V1` stays **FAILED_SCREEN —
RETIRED** (PR #2861). CFB sides/totals stays **permanently closed**
(G3 audit, PR #2851); nothing here reopens it. **Date:** Wed Oct 28,
2026 · **Author:** Rocky (Muse), under the owner's standing
directives (verified-engines-everywhere; iterate with NEW versions on
their own preregistered criteria; no resurrections, no lowered
thresholds).

**Companion records (read first):**
`research/cfb_activation_20261027/DESIGN_CFB_TEAM_TOTALS_V1.md` (the
retired construction), `PREREG_CFB_TEAM_TOTALS_FORWARD_V1_DRAFT.md`
in the same directory (§4.3 = the screen criteria this successor must
meet unchanged), `research/cfb_team_totals_screen_20261028/SCREEN_REPORT.md`
(the failure of record), `research/cfb_activation_20261027/STATUS_NOTE.md`
(current family state).

---

## 1. The failure this design must answer

`CFB_TEAM_TOTAL_POSSESSION_V1` (projected drives × observed points
per drive, NB distribution) failed its §4.3 screen on 2023–2025
(n = 3,172 team-games / 1,586 games), legs 1–3 outright:

| Statistic | v1 | Criterion | Result |
| --- | ---: | ---: | --- |
| Residual beta (pooled) | **−0.0274** | ≥ +0.10 | FAIL (negative all 3 seasons) |
| MAE(M) vs MAE(market-implied split) | 9.453 vs 8.708 | ≤ split + 0.5 | FAIL (Δ +0.745, 95% CI [+0.608, +0.884]) |
| MAE vs naive B1 / B2 | 9.453 vs 10.506 / 10.463 | < both | PASS |
| 80% PI coverage | 0.827 | ∈ [0.72, 0.88] | PASS |

Two facts in that record define what a successor may and may not
claim:

1. **The machinery carries real information; the disagreement does
   not.** v1 beat both walk-forward naive baselines by more than a
   point of MAE — team scoring is modelable from possession data.
   But when v1 disagreed with the market's implied split, actual
   scoring moved slightly *against* it, in every season. The split
   is the market's arithmetic on its own spread and total, and on
   this evidence it already contains what a game-level possession
   model knows.
2. **The screened estimator was not the designed estimator.** The
   v1 design (§2.2) named a *finishing profile* — PPA per play
   (rush/dropback), success rate, explosiveness, Eckel rate and
   points-per-Eckel, red-zone rates — as the points-per-drive
   matchup. The screen's implementer reading R2 (recorded before
   the run, in the open) operationalized that profile as **raw
   observed points per drive**, a shrunk ratio of season aggregates,
   and used the profile statistics as diagnostics only, because the
   design named no fitted form. What failed is therefore precisely:
   a separable product of two shrunk season-rate ratios. What was
   never tested is a fitted mapping from play-level efficiency to
   per-drive scoring. This successor tests exactly that untested
   object — and §7 states the strong prior against it.

A third measured fact: the QB-change stratum (recorded passer differs
from the team's prior game; 26.7% of rows) ran beta −0.0568, worse
than the pooled −0.0274. That stratum was a **pre-registered
reporting item** (v1 prereg §4.4), specified before outcomes were
seen; a successor feature motivated by a pre-registered diagnostic
is design iteration, not post-hoc cohort shopping. §3.3 uses it —
with the arithmetic honesty of §3.3's own paragraph: that term
alone cannot carry the beta leg.

## 2. Claim

**A points-per-drive value fitted from play-level efficiency (EPA
per play and its finishing components), conditional on the game's
projected drive volume and on prior-games-only starter continuity,
predicts a team's scoring distribution more accurately than the
market's implied split of its own game — measurably, in the
disagreement direction (positive residual beta), not merely toward
the naive baselines a rate model already beats.**

If the fitted profile's disagreements with the split are again
anti-signal, the claim is false and §6's stop rule closes the
family on current inputs. The claim is deliberately stated against
the split (the governing baseline), not against B1/B2: beating the
naive baselines a second time would prove nothing new.

## 3. Construction

Target unchanged (it is the family's market, not the failed part):
one team's full-game points including OT, per DraftKings
settlement; two team-game rows per game; NB distribution over the
mean; no market input to the forecast function at any stage.

### 3.1 Play-level efficiency profile (the fitted object v1 never fit)

From cfbfastR play-by-play, per team, walk-forward (games strictly
before the evaluation game's week), the design §2.2 profile computed
as **rates per play**, offense and defense-allowed, each shrunk
toward the FBS league rate with the v1 pooling discipline
(`w = n/(n+3)` on qualifying games, prior-season pool at half
weight — governance machinery carried over, not claimed as new):

- EPA/play (the cfbfastR `ep` field aggregated locally), split
  dropback / rush;
- success rate; explosiveness rate (EPA ≥ 1.0 plays, the cfbfastR
  convention);
- Eckel rate and points per Eckel;
- red-zone trip rate per drive and TD rate per trip;
- drive rate (drives per game) and seconds per play, as in v1.

### 3.2 The fitted finishing map (structural difference #1)

Points per drive is **not** an observed ratio. It is a fitted
function, fit once per evaluation fold on training seasons only
(seasons strictly before the evaluation season), of the matchup
profile:

```
ppd(i,j) = g( EPA_off(i) − EPA_def_allowed(j),
              success_diff, explosiveness_diff,
              Eckel_diff, RZ_trip_rate(i,j), RZ_TD_diff,
              projected_drives(i,j) )          [see §3.4]
```

`g` is a regularized linear model (ridge, penalty fixed in the
screen spec, §5 — not swept) whose target is realized points per
drive on training team-games built under the identical walk-forward
discipline. The fit form, feature list, and penalty are fixed by
this design and the screen spec; inventing a richer form after
seeing the data layout is prohibited by the same fixed-before-data
rule v1's R2 honored. Mean points = projected drives (§3.4) ×
ppd(i,j). This differs from v1 in the unit of estimation: v1's
per-drive value was a descriptive statistic of the team's own past;
v2's is a cross-sectional mapping from efficiency components to
scoring, estimated on thousands of training team-games — the
estimator class the v1 design text named and its screen never ran.

### 3.3 Starter-continuity state (structural difference #2)

v1 measured the QB-change exposure and, by design, never modeled
it. v2 carries one pre-kickoff-knowable state per team, computed
**only from prior games**: `continuity = 1` if the passer credited
with the team's first dropback in its most recent prior game is the
same passer credited in the game before that, else `0` (a team's
first two games of a season take the pool value). The state enters
`g` as a single indicator interacting with the EPA differential —
nothing more. Three honesty constraints, fixed here:

- The input is **who actually started prior games** (PBP-derived,
  the #2861 screen's §3 P2 derivation), never a designation for
  the game being priced. G3 stands: no point-in-time designation
  source exists, and this construction does not pretend otherwise.
  A starter change announced or occurring for the priced game is
  **unknowable** to this construction and remains unmodeled risk.
- The arithmetic ceiling is stated, not hidden: neutralizing the
  stratum entirely (β_stratum from −0.0568 to 0 at its 26.7%
  share) moves pooled beta by ≈ +0.015 — from −0.027 to ≈ −0.012.
  **This term cannot pass leg 1 by itself** and is not the claim;
  it removes a measured drag so the fitted profile's own signal,
  if any, is not masked by it.
- The stratum reporting of v1 prereg §4.4 is retained verbatim in
  the successor screen (§5), so the term's actual contribution is
  measured, not asserted.

### 3.4 Pace × efficiency interaction (structural difference #3)

v1's form was separable by construction: drives(i,j) × ppd(i,j),
each factor a shrunk off/def blend independent of the other.
`projected_drives(i,j)` (v1's R1 arithmetic blend of shrunk
offensive tempo and defensive tempo allowance) enters `g` as a
**feature**, so per-drive value may vary with projected drive
volume — the direction the sport suggests (very high drive counts
co-occur with shootout game scripts, prevent states, and
clock-driven late drives whose per-drive yield differs from a
grinding game's). One interaction, named here; no further
interactions may be added at build time.

### 3.5 Distribution

Negative Binomial over the §3.2 mean, dispersion fit by maximum
likelihood on walk-forward predictions over training seasons only,
one pooled constant per evaluation fold (v1's R6 discipline,
carried over as machinery). 80% intervals from the NB CDF as in v1
R7. This layer held its criterion in v1 (coverage 0.827) and is not
claimed as a difference.

### 3.6 Explicitly NOT used

- **No market line as a feature, at any stage** (carried from v1 §2.2).
- **No starting-QB identity or designation for the priced game**
  (G3; §3.3 is prior-games state only).
- **No CFBD API aggregates.** CFBD's EPA/advanced endpoints sit
  behind the key wall (§4); every efficiency input is derived
  locally from pinned PBP instead.
- **No weather input.** v1 listed CFBD game weather as context; the
  CFBD API is not locally accessible (§4), and no other point-in-time
  CFB weather source is admitted on main. The construction runs
  without it rather than quietly depending on an unadmitted feed.
- **No retrospective ratings** (SP+, FPI, or any as-of-unverified
  snapshot), carried from v1.
- **Nothing from the retired sides/totals constructions** (PM, AM,
  PRIOR_CURRENT_BLEND, CFB_CONVERGED_ANCHOR_V1): no coefficient,
  anchor, blending weight, or joint-score machinery. The target
  remains a single team's distribution, as in v1 §0.

### 3.7 Illinois exclusion

Any game in which either team is an Illinois **college** team is
excluded before pricing or scoring: refused
`ILLINOIS_COLLEGE_EXCLUDED` via `sportsedge/registry_gate.py`
(`artifacts.free_models.IL_COLLEGE_NAMES`), excluded from every
denominator, and counted in the exclusion report (v1 §2.5, carried
verbatim).

## 4. Data basis and admission status, per source

| Source | Use | Status on main |
| --- | --- | --- |
| SDV `cfb_schedules` release assets (sportsdataverse-data) | Settlement (final team points incl. OT), joined on game_id | **Admitted DESIGN baseline** — the converged screen's pinned source, re-pinned by sha256 in PR #2861 (`PINS.json`); read as published |
| SDV `betting` release assets | Closing spread/total → the governing market-implied split | **Admitted DESIGN baseline** (same pinning lineage). Untimestamped snapshots → design evidence only; beating them is never "verified CLV"; any ROI framing would carry the flat −110 ASSUMPTION label (this screen computes no ROI) |
| cfbfastR play-by-play via the sportsdataverse-data mirror release (`cfbfastR_cfb_pbp`), 2021–2025 | All §3.1 profile inputs; drive derivation; §3.3 passer derivation | **Screen-grade DESIGN data** — hash-pinned and used in PR #2861; the mirror covers all divisions, so the FBS scope filter of #2861 §3 P2 applies (plays restricted to games with ≥1 FBS team before derivation). The cfbfastR-data release route returned 404 throughout #2861's re-pull window and its git tree carries PBP only through 2021 — the mirror is the route of record, with the two-execution vintage disclosure of #2861 §7 standing as the caution |
| CFBD betting lines 2013+ | Cross-check extract for close identity only | **Admitted DESIGN baseline** (G3 audit, PR #2851). Not the governing baseline; CFBD explicit team-total fields, if present at pin time, are recorded and cross-checked, never substituted (v1 design §3.1 rule) |
| CFBD API (EPA / advanced box / weather endpoints) | **Not used** | **NOT locally accessible** — the API answers 401 unauthenticated and no key exists in the local environment (verified in PRs #2831/#2861); keys exist only as repo secrets consumable inside Actions runs. The construction is specified to need nothing from this API |
| DraftKings explicit CFB team-total lines | Forward baseline only, if a freeze ever follows | **Not yet captured** — the v1 prereg §3 arming precondition (lane CFB issue grammar must carry explicit TeamTotal lines, both teams, both sides, T-1H / FINAL cadence) is unchanged and still owed; it is a forward-test precondition, not a screen input |

Training reach: profile/map fitting may reach back to 2021 (the
pinned PBP window); evaluation seasons are 2023–2025 (§5).

## 5. Design-screen spec (fixed before any run; one run; no sweeps)

**Cohort** (identical to v1 prereg §4.1): FBS vs FBS only; Week 5+;
≥3 qualifying prior games per team; Illinois-college games excluded
per §3.7; expanding-window discipline — features from games strictly
before the evaluation game's week (§4.1's week keying, v1 R8);
every fitted object (the §3.2 map, the NB dispersion) fit only on
seasons strictly before the evaluation season. Identical-rows
discipline: every arm scored on exactly the same team-game rows.

**Arms:** M (this construction); B-MKT (close-implied team total,
the §4 identity `implied_home = (T + S_close)/2`,
`implied_away = (T − S_close)/2`, sign convention proven from the
collector code on sampled rows at pin time, as #2861 §3 did);
B1 (team's walk-forward season-to-date mean points); B2
(walk-forward FBS league mean points per team-game).

**Pass criteria — the v1 prereg §4.3 legs, verbatim, no leg softer:**

1. Pooled residual beta ≥ **+0.10** (pooled OLS slope with intercept
   of `(actual − B-MKT)` on `(M − B-MKT)` over both team rows).
2. Beta > 0 in at least **2 of 3** evaluation seasons.
3. Pooled MAE(M) ≤ MAE(B-MKT) **+ 0.5**, **and** MAE(M) < MAE(B1)
   and MAE(M) < MAE(B2) (point estimates).
4. At least **100 games per evaluation season** in the cohort.
5. Pooled empirical coverage of M's 80% prediction intervals within
   **[0.72, 0.88]**.

**Required reporting (pass or fail):** per-season and pooled n,
beta, MAEs for all arms, interval coverage; the QB-sensitivity
stratum with its own beta/MAE (reporting only, never a cohort
trim); the continuity term's fitted coefficient per fold; the
Illinois-exclusion count; the full exclusion accounting table in
the converged screen's format; game-cluster bootstrap interval on
ΔMAE(M − B-MKT) as reporting-only context (no criterion uses an
interval, as in v1). One execution on hash-pinned inputs; if an
execution is lost or its inputs cannot be re-pulled identically,
#2861 §7's pre-committed rule governs (a pass that a second
execution contradicts is recorded NOT-EXECUTABLE/contested, never
pooled).

**Verdicts:** `SCREEN_PASS` — all five legs hold; effect: the
construction earns the right to *request* an owner freeze of a
forward test drafted as a revision of the v1 prereg (whose §§5–11
terms are proposed there unchanged). `SCREEN_FAIL` — any leg
fails; effect: FAILED_SCREEN, retired, and §6's stop rule applies.
A screen pass is design evidence only; verification under the
owner's Oct 27, 2026 definition accrues forward only, against the
existing model and the contemporaneous DK market — the historical
existing-model leg is represented by B1/B2 here and binds forward,
the asymmetry stated in v1 design §3.2, restated not smoothed over.

## 6. Known failure risks, and the stop rule

1. **The split may simply be unbeatable on public inputs (the
   governing risk).** The implied split is a deterministic function
   of two market numbers set with full public information —
   including the same EPA data this construction fits. v1's beta
   was negative in all three seasons; the NFL sibling construction
   (NFL_TEAM_TOTAL_DIST_V1, a different estimator on a different
   league) also loses clearly to its implied split (MAE 7.749 vs
   7.250). Two independent failures of the same structural fact is
   the prior. The fitted profile plausibly tightens MAE *toward*
   the split without creating positive beta — legs 3 could pass
   while legs 1–2 fail, which is still SCREEN_FAIL.
2. **Fit-form risk.** A ridge over a dozen profile features fit on
   three training seasons can absorb season-specific noise;
   walk-forward fitting and the fixed penalty bound this but do not
   eliminate it. The per-season beta leg (≥2 of 3 positive) is the
   designed tripwire.
3. **Unmodeled starter risk remains.** §3.3 sees continuity of
   *past* starters only. The priced game's actual starter —
   including the 15–19% late-change class the G3 audit measured —
   is invisible to this construction by data law, not by choice.
4. **PBP vintage risk.** The mirror is a rolling release lineage;
   #2861 needed two executions on different vintages to establish
   its verdict. §5's contested-pass rule is the mitigation.
5. **Cohort overlap.** 2023–2025 are design data seen by v1's screen
   and the retired constructions. Nothing in a pass here is
   validation; the forward test is the only verdict that counts.

**Stop rule (pre-committed):** if this construction fails §5, the
CFB team-total family is recorded **NO_VIABLE_CONSTRUCTION on
current admissible inputs** — the possession line (v1) and the
profile line (v2) both exhausted — and reopens only on a genuinely
new input class (a point-in-time designation record per G3's
re-audit triggers, or an admitted explicit team-total line archive),
never on a third estimator over the same inputs.

## 7. Honest readiness verdict

**VIABLE TO SCREEN — with a negative prior, stated in the open.**
The one estimator the v1 design actually named was never run; the
screen is one fixed-criteria execution on already-pinned data; and
the stop rule above makes a second failure cheap and final rather
than the start of a tuning loop. The expected outcome, on the
evidence of §6.1, is failure — this design is delivered so that the
family's last untested structural idea is tested cleanly or the
family closes honestly, not so it can be tuned toward a pass.

**What would falsify this design (before any screen):** a pin-time
finding that the mirror PBP cannot reproduce #2861's cohort under
the FBS filter (inputs not stable enough to screen); or a
predecessor-record correction showing the §3.2 profile *was* in
fact the screened estimator (which would collapse the structural
difference and reduce this document to a retune brief — prohibited).

## 8. Path from this draft (checklist)

- [ ] Independent review of this design by a checker who did not
      draft it.
- [ ] Screen built to §5 (hash-pinned inputs), run once, verdict
      and full reporting committed as its own record.
- [ ] If SCREEN_FAIL: stop; family recorded per §6's stop rule.
- [ ] If SCREEN_PASS: forward prereg revision drafted from the v1
      prereg (terms unchanged), lane TeamTotal capture proven
      (§4 arming precondition), evaluator pinned and reviewed,
      owner freeze requested. **None of that is requested here.**
