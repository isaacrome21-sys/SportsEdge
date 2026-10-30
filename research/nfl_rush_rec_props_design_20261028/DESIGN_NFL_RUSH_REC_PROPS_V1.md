# DESIGN — NFL Rushing & Receiving Props: `NFL_RUSH_REC_PROPS_V1`

**Status: DESIGN + PREREGISTERED SCREEN — NOT BUILT, NOT SCREENED, NOT
FROZEN.** This document specifies a construction, and fixes the design
screen it must pass before any of it is built or any outcome is computed.
Nothing here prices a game, opens a clock, starts a count, changes a
registry entry, or requests a freeze or adoption. **Date:** Wed Oct 28,
2026 · **Author:** Grok Bot, in the lane the owner assigned
(NFL rushing + receiving player props).

**Scope:** RUSH_YDS (`player_rush_yds` / `rushing_yards`), REC_YDS
(`player_reception_yds` / `receiving_yards`), RECEPTIONS
(`player_receptions` / `receptions`). **Out of scope, untouched:**
passing yards (own v2 screen,
`research/nfl_passyds_v2_screen_20261027/`), anytime TD (frozen), first
TD (retired), and the combo / count families built in
`research/nfl_prop_engines_20261020/` (rush+rec yards, targets,
rush attempts).

**Companion records (read first):**
`research/nfl_props_part2_20261018/PREREG_NFL_PROPS_CALIBRATION_V1.md`
and `REPORT.md` (the incumbent's historical screen of record),
`PREREG_NFL_PROPS_PART2_FORWARD_V1.md` (the incumbent's FROZEN forward
terms, incl. the §5 / issue #2388 under-tilt rule), and
`AMENDMENT_B8_SP2025_REPIN_20261026.md` (the 2025 file re-pin).

---

## 1. The incumbent, and the weakness this design must answer

The incumbent for these three markets is the Part 2 construction
(evaluator `eval_nfl_props_calibration_v1.py`, sha256
`66de5615…bc25b`): per player, μ = (Σ prior same-season values + 3·G) /
(n + 3), G = the league role-pool mean; distribution Gamma (yards) or
NB (receptions) with **one pooled CV per market** fit on 2018–2019.
It is **not failed** — it is CALIBRATED_CANDIDATE on all three markets
(Oct 17 screen, 2020–2025: CRPS 19.46 / 18.33 / 1.282 vs best baseline
20.84 / 19.67 / 1.380) and is under a frozen forward test. This design is
a **challenger**, not a successor to a retired construction; it changes
nothing about the incumbent or its forward test.

The weakness of record (incumbent `REPORT.md`): the model is
**overconfident in its most extreme decile**, "most clearly on receiving
yards (says 71%, realized 60%) and receptions (63% vs 54%)". A single
pooled CV gives a 3-target slot receiver and a 10-target WR1 the same
relative spread, and a stat-level shrunk mean cannot tell whether a
player's history is volume or efficiency. Those are the two things this
design changes.

## 2. Claim

**Decomposing each stat into opportunity (the player's share of his
team's carries or targets × the team's volume) and efficiency (yards per
opportunity, catch rate), each shrunk at its own rate, and deriving each
player-game's spread from that decomposition rather than from one pooled
CV, gives better-calibrated predictive distributions than the incumbent
— better CRPS overall, and smaller error in the extreme deciles where
the incumbent is overconfident.**

If the decomposition does not beat the incumbent on the incumbent's own
population and data, the claim is false and the construction retires.

## 3. Construction

All inputs are point-in-time: only the player's and his team's games in
**strictly earlier weeks of the same season** (the incumbent's sample
rule). Training-only constants come from 2018–2019 alone. No market
price is an input anywhere.

### 3.1 Opportunity

- **Team volume V** (per team-game): team carries (RUSH_YDS) or team
  targets (REC_YDS, RECEPTIONS) = sum over that team's rows in the
  weekly file for the game. V̂ = (Σ prior team-game V + K_V·L) / (n_t +
  K_V), K_V = 4 games, L = the league mean team V over all team-games in
  strictly earlier weeks of the season (previous season's full set for
  the opening weeks — the incumbent's `league_pool` fallback rule).
- **Player share s** (per played game): player carries / team carries,
  or player targets / team targets. ŝ = exponentially weighted mean of
  the player's prior played-game shares, half-life **3 games**, shrunk
  toward the role-pool mean share S (same pool definition as G) with
  K_S = 2 games of weight: ŝ = (Σw·s + K_S·S) / (Σw + K_S).
  Rationale stated here, before any run: share is a role, roles change
  inside a season, so recent games weigh more; efficiency (§3.2) is not
  recency-weighted.
- **Expected opportunities** n̂ = ŝ · V̂.

### 3.2 Efficiency

- **Yards per opportunity** ê: (Σ prior yards + K_E·E) / (Σ prior
  opportunities + K_E), with E = role-pool yards per opportunity (pool
  rule as G) and K_E = **60 carries** (RUSH) / **50 targets** (REC).
  Opportunity-weighted, not game-weighted.
- **Catch rate** p̂ (RECEPTIONS only): (Σ prior receptions + K_C·P) /
  (Σ prior targets + K_C), P = role-pool catch rate, K_C = 50 targets.

### 3.3 Predictive distribution (the structural break)

- **Opportunities** N ~ NB with mean n̂ and variance n̂ + n̂²/r_N, where
  r_N (one per market) is fit by method of moments on 2018–2019
  qualified player-weeks only.
- **Yards** Y = sum of N per-opportunity gains. Mean n̂·ê; variance
  n̂·σ² + ê²·Var(N), where σ² (one per market) is the per-opportunity
  yardage variance estimated on 2018–2019 by method of moments from
  game logs: σ² = mean over qualified player-weeks of
  (Y − N·ê)² / N for N > 0. Distribution: Gamma moment-matched to that
  mean and variance — the same family as the incumbent, so any
  difference comes from the mean and the player-specific spread, not
  from a change of family.
- **Receptions** R | N ~ Binomial(N, p̂), N ~ NB as above; the CDF is the
  exact mixture over N (N truncated where its tail mass < 1e-9).
- The relative spread therefore varies with each player's volume and
  efficiency; there is **no pooled CV** anywhere in the construction.

### 3.4 What this construction is not

- **Not a retune of the incumbent.** K = 3, the pooled CV, and the
  stat-level shrunk mean are not used; no incumbent constant is reused.
- **Not the #2388 role-conditional-pool v2.** The incumbent's frozen
  forward prereg §5 reserves "role-conditional pools (WR1s against
  WR1s)" as a separately preregistered v2, decided by its stratified
  readout. This design does not condition pools by role tier and does
  not pre-empt that ruling.
- **Not a market model.** No line, price, or derived market quantity is
  a feature.
- **Not a PBP model.** Play-by-play is not an input (§4).

## 4. Data basis and admission status, per source

| Source | Use | Status on main |
| --- | --- | --- |
| nflverse weekly player stats `ps_2018`–`ps_2024.csv.gz` | Every player and team quantity in §3 (carries, targets, receptions, rushing_yards, receiving_yards, position, team, week) | **Pinned** in `research/nfl_props_part2_20261018/SPEC_HASHES.txt` (the incumbent's file set); the screen hash-verifies every file and refuses on mismatch. Locally re-verified Oct 28: all seven ps files match their pins |
| `sp_2025_played_v2.csv.gz` | 2025 rows | **Pinned** (`f2768ac1…f7b48`, B8 amendment); built deterministically from the original `sp_2025.csv.gz` (`c7401e32…eac0b`, verified locally) by `build_sp_2025_played_v2.py`. Removed rows are zero carries/targets, so team volumes are unaffected |
| Incumbent evaluator `eval_nfl_props_calibration_v1.py` | The INC arm, B1, B2, CRPS, bootstrap | On main, sha256 `66de5615…bc25b`; imported after a hash check, never modified |

**Column mapping fixed here:** team identity is `recent_team` in ps files
and `team` in the sp file; rows are regular season only
(`season_type == REG`); a team-game is (season, week, team). The
missing-cell rule is the incumbent loader's (`f()`: blank → 0.0) for
stat cells. A team-game whose summed V is 0 contributes no share
observation (and is reported).

**Not used, and why:** nflverse play-by-play (hash-recorded in the NFL
activation screen but with no standalone admission record on main);
snap counts / participation (not in the pinned snapshot); injury and
depth-chart feeds; any historical prop prices (**none exist on main or
in any admitted source** — the incumbent `REPORT.md` says so).

## 5. Design screen — fixed before any build or result

**Window:** fit 2018–2019 (r_N, σ² only); score **2020–2025, weeks ≥ 4**,
regular season — the incumbent screen's window.

**Population (paired):** exactly the incumbent's qualified rows per
market (RUSH_YDS: mean prior carries ≥ 8 over ≥ 3 prior games;
REC_YDS / RECEPTIONS: mean prior targets ≥ 4 over ≥ 3 prior games),
taken from the incumbent's own `build()` on the pinned file set. Every
arm scores every row. A row M cannot price is a **build defect**, not an
exclusion; more than 0.5% unpriceable rows in any market makes that
market NOT_EXECUTABLE.

**Arms:** M (this construction); **INC** (the incumbent, via its
pinned functions — the bar); B1 (player's own prior empirical CDF); B2
(league role-pool empirical CDF). Grid and CRPS exactly the incumbent's
(`GRID_LO = −60`, `GRID_HI = 700`, `crps()`).

**Pass criteria, per market (never pooled across markets):**

1. **Beats the incumbent:** mean ΔCRPS (M − INC) < 0 with the
   season-week block-bootstrap 95% CI upper bound < 0 (incumbent
   `boot()`, 2,000 resamples, seed **20261028**).
2. **Beats both baselines:** ΔCRPS vs B1 and vs B2, each CI upper < 0
   (the incumbent's own criterion, unchanged).
3. **Extreme-decile leg (the claim's leg):** at the incumbent's line
   proxy (floor(median of prior values) + 0.5), sort rows by M's
   P(over); in the top and bottom deciles,
   |mean P(over) − realized over-rate| must be **≤ 0.05** in each
   **and** no larger than INC's gap in the same decile computed the
   same way. Rationale stated now: the incumbent's documented weakness
   is the extreme decile; a challenger that wins CRPS while staying as
   overconfident there has not answered its own claim.
4. **Stability leg:** in no scored season does M's mean CRPS exceed
   INC's by more than **1%** of INC's mean CRPS for that season.

**Integrity checks (run before any M score is read; failure →
NOT_EXECUTABLE):** all file hashes match; the incumbent evaluator hash
matches; the INC arm on 2020–2024 rows reproduces the incumbent
evaluator's own output for those rows exactly (same rows, same CRPS);
the team-volume reconstruction is reported (distribution of team-game V,
count of zero-V team-games); r_N and σ² come from 2018–2019 rows only
(asserted in code).

**Required reporting:** per market — n, CRPS by arm, the three ΔCRPS
with CIs, per-season CRPS for M and INC, line-proxy deciles for M and
INC, PIT histogram for M, fitted r_N and σ², and the share of rows where
n̂ was driven mostly by the prior (Σw < K_S).

**Verdicts (per market):** `SCREEN_PASS` — all four legs hold; effect:
the construction may be **named** in a separate forward preregistration
draft (§8) and nothing more. `SCREEN_FAIL` — any leg fails; that market's
construction is FAILED_SCREEN and retired for that market; no retune,
no re-bucketing, no constant change. `NOT_EXECUTABLE` — an integrity
check failed; the record says which, and nothing is scored.

**Status of a pass:** 2020–2025 are seen seasons (the incumbent was
screened on them), so a pass is a **design-data entry ticket, never
validation**. Under the owner's Oct 27 definition, verification needs
preregistered validation against model **and market**; no historical
market leg exists for these props (§6.4), so the market question is
answered only forward (§8).

## 6. Known failure risks

1. **Share noise early in the season.** By week 4 a player has 3 prior
   games; a recency-weighted share is noisy there, and the role-pool
   prior may dominate — which can make M no better than INC exactly
   where props are first priced.
2. **Team volume is game-script driven.** Team carries and targets
   swing with score state; game logs cannot see script. Using it as a
   shrunk mean may add noise rather than signal.
3. **Gamma on rushing yards.** Rushing yards can be negative; both M and
   INC put zero mass below 0. Shared limitation, not a comparative
   advantage; reported, not fixed.
4. **No historical market leg.** No historical prop prices exist in the
   repo or any admitted source, so this screen measures model quality
   only. Reading a pass as market evidence is a misreading.
5. **Thin efficiency cells for backups.** K_E = 50–60 opportunities
   means low-volume players' efficiency is almost entirely the role
   pool's — by design.

## 7. Ambiguity rule

Where this design leaves an implementation detail open (e.g. how to
handle a player traded mid-season: share uses his current team's
prior team-games while he was on it, efficiency uses all his prior
games), the build must record its reading **in the screen record
before computing any outcome statistic**, and may not change it after.
An ambiguity found to change a verdict is reported, not silently
resolved.

## 8. Forward preregistration skeleton (no terms written here)

On a SCREEN_PASS for a market, a **separate** forward preregistration
draft would name `NFL_RUSH_REC_PROPS_V1`, its sha256 pins (design,
engine, fitted constants), and the screen result, and would run against
captured two-sided DraftKings prices under the capture, de-vig, CLV and
missing-close conventions of the incumbent's frozen Part 2 forward
prereg (§2–§4.5), as a separate test with its own sample — never
pooled with or counted toward the incumbent's rows. That draft, its
review, and any freeze are later steps; **freeze is the owner's act**,
and none is requested here. Until then, family state for this
construction is DESIGN ONLY; counted rows zero.

## 9. Honest readiness verdict

**VIABLE TO SCREEN** on data already pinned in the repo. The bar is
high — the incumbent already beats both baselines by clear margins, and
legs 1 and 3 require beating it outright and fixing its known
overconfidence. A fail would close the usage × efficiency direction for
these markets on game-log inputs, leaving richer inputs (admitted PBP,
participation data) as the only remaining route.

## 10. Path from this draft (checklist)

- [ ] Independent review of this design by a checker who did not draft it.
- [ ] Owner decision whether to proceed to build.
- [ ] Build the construction + screen script with §7 readings recorded;
      run integrity checks; screen once per §5; commit the verdict.
- [ ] If SCREEN_FAIL: stop; construction retired for that market.
- [ ] If SCREEN_PASS: forward prereg draft per §8; review; owner
      freeze ruling. **None of that is requested here.**
