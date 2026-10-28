# DESIGN — NFL Period Lines Successor: `NFL_PERIOD_DRIVE_STATE_V2`

**Status: DESIGN — NOT BUILT, NOT FROZEN.** This document specifies
a construction, the screen it must pass, and a forward-preregistration
skeleton that binds to terms already drafted. Nothing in it prices a
game, opens a clock, or starts a count. `NFL_PERIOD_SHARE_V1` stays
**FAILED_SCREEN** (activation pack, PR #2852); the retired
`sportsedge/market_coverage.py` quarter pricers stay
NOT_WIRED_WITH_REASON. **Date:** Wed Oct 28, 2026 · **Author:**
Rocky (Muse), under the owner's standing directives
(verified-engines-everywhere; new versions only, on their own
pre-committed criteria).

**Companion records (read first):**
`research/nfl_activation_20261027/DESIGN_NFL_PERIOD_LINES_V1.md`
(the failed construction and the family's named path — this design
is its §5 step 3), `SCREEN_REPORT.md` in the same directory (the
screen of record, incl. the period panel's construction and
integrity checks), and `PREREG_NFL_PERIOD_LINES_FORWARD_V1_DRAFT.md`
in the same directory (the family's forward terms, already fixed —
§8 of this design binds to them).

---

## 1. The failure this design must answer

`NFL_PERIOD_SHARE_V1` split the sibling team-total mean by each
team's own historical quarter shares (150-point shrinkage toward
league shares, ~8-game samples). Screen, 2023–2025, n = 1,632
team-games, criteria fixed before the run — pooled MAE candidate
**4.444** vs B0 (league shares) **4.423** vs B1 (flat split) 4.469;
the candidate beat B0 in only 2 of 6 buckets:

| Bucket | Candidate | B0 league shares | B1 flat |
| --- | ---: | ---: | ---: |
| Q1 | 3.517 | 3.519 | 3.672 |
| Q2 | 4.261 | 4.246 | 4.279 |
| Q3 | 3.635 | 3.636 | 3.727 |
| Q4 | **4.314** | **4.257** | 4.269 |
| 1H | 5.450 | 5.439 | 5.423 |
| Pooled | 4.444 | 4.423 | 4.469 |

The diagnosis is in the record and this design accepts it verbatim:
a team's quarterly points over ~8 games are a few dozen scoring
events, so its share profile is noise; and **Q4 — the worst bucket —
is state-driven** (trailing teams hurry and allow more; leading
teams trade yards for clock), which no share profile of any sample
size can see, because a share has no game state in it. What failed
is share-profile modeling. The untested proposition is the design
doc's second claim: that period scoring is a *drive-level,
state-conditioned* process, and modeling it as one produces period
distributions a fixed share cannot.

## 2. Claim

**Simulating a game drive by drive — with pace, play selection, and
scoring rates conditioned on score differential and time remaining —
produces quarter and first-half scoring distributions more accurate
than the league-share decomposition (B0), including in Q4, where the
state distribution is widest and the share model's error is largest.**

Period markets are two-team objects (a quarter total is a sum, a
quarter spread a difference), so the construction emits, per game, a
**joint distribution over the four quarters' points for both teams**
(the forward draft's §2 requirement) — never eight independent
marginals. If the simulated state dynamics do not beat a static
share table, the claim is false, on the bucket (Q4) where the
mechanism is supposed to live (§5 makes that a named leg).

## 3. Construction

### 3.1 Drive-level simulation (the structural break from v1)

A game is simulated as a sequence of drives under a game clock.
Each drive is generated from point-in-time team rates (§3.3) and
the current game state (§3.2):

- **Possession alternation** with kickoff outcomes after scores and
  half boundaries handled as the rules dictate (opening coin-flip
  team order fixed from the schedule record; second-half kickoff to
  the other team).
- **Drive outcome model:** starting field position drawn from the
  possessing team's point-in-time kickoff/punt return-and-coverage
  distribution; the drive then advances play by play or in
  drive-aggregate form (build choice fixed at build time and
  recorded — §7's ambiguity rule) with per-play gain, turnover, and
  penalty rates from the offense-vs-defense matchup; the drive ends
  in TD / FG / punt / turnover / downs / half-or-game expiry, with
  end-of-half and end-of-game clock states allowed to truncate it.
- **Clock consumption:** every play consumes seconds drawn from the
  state-conditioned pace distribution (§3.2); a quarter boundary is
  a clock event, not a scoring reset — **a drive in progress at a
  quarter break continues**, and its points land in the quarter the
  score occurs. (This is the mechanical fact share models cannot
  express and the panel in the screen record measures directly.)
- **Outputs per replication:** both teams' points by quarter.
  R = 10,000 replications per game at a fixed seed (seed and R
  fixed in the screen spec, §5 — simulation size is a criterion
  input, not a tuning knob). Period means are replication means;
  period probabilities come from the empirical joint distribution
  (pushes at whole lines handled by the forward draft's settlement
  conventions at forward time; the screen scores means).

### 3.2 Game-state conditioning (the mechanism under test)

State = (score differential from the possessing team's perspective,
time remaining in the half, timeouts remaining where the PBP records
them). State modulates exactly three things, each as a
point-in-time league-level function estimated on training seasons
only, with team rates entering through §3.3:

1. **Pace:** seconds-per-play distribution by state bucket —
   trailing-late hurry-up and leading-late clock bleed are the two
   poles; the two-minute drill is the extreme of the first.
2. **Play selection:** pass probability by state bucket (trailing
   teams pass; leading-late teams run into loaded boxes and accept
   it).
3. **Scoring environment:** per-play gain and explosive-play rates
   scaled by state bucket (prevent defense concedes underneath
   yardage while suppressing explosives; desperate offenses invert
   both).

State buckets are fixed here, before any run: differential in
{≤ −17, −16…−9, −8…−3, −2…+2, +3…+8, +9…+16, ≥ +17} × time in
{first half, Q3, Q4 > 5:00, Q4 ≤ 5:00, Q4 ≤ 2:00}. No bucket may be
added, split, or merged after the screen's inputs are pinned.
Team-specific state behavior is **not** modeled (three seasons of
PBP cannot support team × state cells; claiming otherwise would
repeat v1's sample-size error one level down) — state functions are
league-level; team identity enters only via §3.3's rates.

### 3.3 Team rates (point-in-time inputs)

Per team, from games strictly before the priced game (the sibling
team-total construction's sample rule: same-season priors
supplemented by prior-season games to 8), fit/derived from nflverse
play-by-play: per-play gain distribution parameters (rush/pass),
turnover rates, penalty rates, drive-start field-position
distribution, base pace (seconds per play, state-neutral), and
red-zone finishing rates. Shrinkage toward league rates follows the
sibling construction's points-scale discipline. The full-game level
is anchored for coherence, not copied: the simulation's implied
full-game team means are reported against `NFL_TEAM_TOTAL_DIST_V1`'s
means on identical games as a **coherence diagnostic** (a period
construction whose game totals drift far from the frozen sibling's
is mis-built, whatever its period MAE says); the sibling's means
are not an input to the simulation.

### 3.4 What this construction is not

- **Not a share model.** No quarter share is an input or a fitted
  object anywhere; period points exist only as simulation output.
- **Not the retired market_coverage pricers.** Those split a
  full-game margin proxy by declared fractions and failed their
  harness (quarter totals Brier 0.2409 vs naive 0.2239); no
  fraction, proxy, or code path is shared.
- **Not an in-play model.** All inputs are pregame and
  point-in-time; the state conditioning is over states the
  *simulation* visits, never the priced game's realized state.
  Second-half lines stay out of scope (in-play prices; the live
  family's territory, per the v1 design §1).

## 4. Data basis and admission status, per source

| Source | Use | Status on main |
| --- | --- | --- |
| nflverse play-by-play, 2023–2025 season files | Drive/play rates, state functions, and the period panel (quarter points from PBP running scores, per the screen record's construction) | **Screen-grade DESIGN data** — pulled and hash-recorded in the activation screen (`SCREEN_REPORT.md` input table: 2023 `bd348473…`, 2024 `3fd2896b…`, 2025 `c6ecedd6…`). Rolling release assets: the hash of the pull used is the provenance, and drift is disclosed, per that record's practice. No standalone PBP admission record exists on main; this design relies on the merged screen record as the lineage, and says so |
| nflverse schedules (`games.csv.gz`) | Game universe, finals for coherence checks, OT exclusion | **Admitted DESIGN baseline snapshot** — pinned in PR #2831 (`DESIGN_BASELINES_PIN_RECORD.md`; the file is a living snapshot subject to drift, sha256 `82b05d70…` at pin, `1b4ca0c7…` at the activation screen's pull — gap G7: design-grade only) |
| The activation pack's period panel builder (`screen_nfl_activation_v1.py`) | Panel reconstruction for the screen (quarter points; 97.0% of team-games match finals exactly, the 3.0% differing only by OT scoring, which the panel excludes by construction) | **On main** (PR #2852); its integrity checks are part of the screen record and are re-run, not assumed, by any successor screen |
| DraftKings period lines (entry + close) | Forward baseline only | **Not yet captured as priced material** — period lines today live in game-issue line-3 comments, verbatim and unpriced. Capture expansion + intake-grammar extension are the family path's steps 1–2 (v1 design §5) and remain **open preconditions** of any forward test; they are not screen inputs |

No other source is used. In particular no market line of any kind
(full-game or period) is an input to the construction.

## 5. Design-screen spec (fixed before any run; one run; no sweeps)

**Window:** 2023–2025 — the predecessor's evaluation window, so the
verdict is comparable to v1's on identical seasons and the same
panel discipline (n = 1,632 team-games expected; the exact cohort
is whatever the panel integrity checks pass, reported in full).
These seasons are DESIGN data (seen by v1 and the retired
constructions); a pass is an entry ticket, never validation.

**Arms:** M (this construction's period means, §3.1);
B0 = sibling full-game mean × point-in-time league shares (the
baseline that beat v1 — the bar); B1 = sibling mean × flat split
(0.25/quarter, 0.50/half). The sibling mean is
`NFL_TEAM_TOTAL_DIST_V1`'s, as in v1's screen, so the comparison
isolates the period mechanism. Buckets: Q1, Q2, Q3, Q4, 1H, and
regulation 2H as a diagnostic only (out of family scope, as in
v1's screen).

**Pass criteria — v1's criteria, with one leg added, none softened:**

1. Pooled MAE(M) < MAE(B0) **and** pooled MAE(M) < MAE(B1) (point
   estimates) — v1's pooled legs, unchanged.
2. M beats B0 in at least **4 of 6** buckets — v1's bucket leg,
   unchanged.
3. **Q4 leg (new, and stricter):** MAE(M) < MAE(B0) in Q4
   specifically. Rationale stated here, before the run: Q4 is
   where the construction's claimed mechanism lives and where v1's
   error was worst; a v2 that passes pooled while still losing Q4
   has reproduced v1's result with more machinery and has not
   answered its own claim.
4. **Stability leg (new):** in no evaluation season is pooled
   MAE(M) worse than that season's MAE(B0) by more than 0.25 (the
   guard the sibling team-total screen carried; added here so a
   single-season artifact cannot carry the pooled verdict).

**Simulation discipline:** seed fixed at screen build and recorded;
R = 10,000 replications per game; the full screen is executed a
second time at a second pre-declared seed and both verdicts
reported — a verdict that flips with the seed is recorded
NOT-EXECUTABLE/contested, never averaged (the #2861 two-execution
rule, applied to simulation variance).

**Required reporting:** MAE by bucket × arm (the v1 table's shape),
per-season pooled MAEs, the Q4 bucket's state-conditional error
breakdown (realized margin entering Q4, in the §3.2 differential
buckets — reporting only), the §3.3 coherence diagnostic vs the
sibling's full-game means, panel integrity results, and both seeds'
verdicts.

**Verdicts:** `SCREEN_PASS` — all four legs hold under both seeds;
effect: the construction may be **named** in a revision of the
forward draft (§8) and a freeze *requested* — nothing more.
`SCREEN_FAIL` — any leg fails; effect: FAILED_SCREEN, retired; a
further successor would need a mechanism this design does not
contain, not a re-bucketing of this one.

## 6. Known failure risks

1. **The state signal may already be in the league shares.** B0 is
   a static table, but it is a static table *of realized state-
   averaged outcomes* — the average Q4 share already contains the
   average game's state dynamics. The construction must beat the
   average with game-specific state distributions (a blowout-prone
   matchup's Q4 is not the average Q4). That is a genuinely harder
   bar than "model the state effects," and it may not clear.
2. **Clock-model error compounds.** Drive durations are drawn, not
   known; small per-play pace errors accumulate into quarter-
   boundary misallocations — points credited to the wrong quarter
   hurt period MAE twice (once missing, once excess) while leaving
   full-game accuracy untouched. The screen can therefore fail a
   construction whose game-level engine is sound; that is the
   family's question, not an excuse.
3. **Thin state cells.** Late-and-close and late-and-blowout states
   are where the mechanism lives and where three seasons of PBP
   offer the fewest drives per team — mitigated by league-level
   state functions (§3.2), at the cost of assuming state behavior
   is a league trait, which is itself a modeling bet stated here.
4. **No historical market leg exists.** Period lines were never
   captured historically; the screen's baselines are model
   baselines (B0/B1), not prices. As with the sibling's screen,
   anyone reading a pass as market evidence is misreading it — the
   market question exists only forward, against captured DK period
   lines, under §8's terms.
5. **Build complexity.** A drive simulator has more places to be
   quietly wrong than a share table (possession bookkeeping, half
   boundaries, kneel-downs, OT exclusion). The panel integrity
   checks and the §3.3 coherence diagnostic are the named guards;
   a build that cannot reproduce the panel's 97.0%-exact / 3.0%-OT
   accounting from its own machinery does not proceed to the screen.

## 7. Ambiguity rule

Where this design leaves a functional form open (drive-aggregate vs
play-by-play drive generation is the named instance), the build
must record its reading **before** computing any outcome statistic,
in the screen record, and may not change it after — the discipline
the CFB screen's §4 readings established. An ambiguity discovered
to change the verdict is reported as such, not resolved silently.

## 8. Forward preregistration skeleton (binds to existing terms; no new terms written here)

The family's forward terms already exist and are **not** revised by
this design: `PREREG_NFL_PERIOD_LINES_FORWARD_V1_DRAFT.md` fixes
per-market verdicts (never pooled), markets in scope (quarter +
1H spread/total/ML/team-total; 2H out), gates (≥100 graded rows AND
≥40 distinct games AND ≥4 full slates per market), the pick rule
(|gap| ≥ 1.5 quarter / ≥ 2.0 1H; ML ≥ 0.04 over entry no-vig),
the §6 legs (CLV primary; accuracy vs the Lane A standing baseline —
`team_half_pricing.py` derivatives for 1H, B0 for quarters;
calibration with the top-decile overconfidence kill), the Part 2 /
v1.1 moved-row and close-validity rules, the α/k accounting, and
the one-review anti-peeking rule. The skeleton is therefore short:

- **§2 binding (the only substantive act):** on a SCREEN_PASS under
  §5, a revision of that draft names `NFL_PERIOD_DRIVE_STATE_V2`,
  its `model_version`, and its sha256 pins (design, engine,
  constants incl. the §3.2 state functions and seed), and records
  the screen result. The framework config
  `sportsedge/forward_validation/configs/nfl_period_lines.json`
  keeps `model_version: "UNPINNED"` until that revision; every row
  is refused fail-closed in the meantime.
- **Open preconditions (unchanged, from the draft's §10):**
  capture expansion (period board as priced entry/close material)
  and intake-grammar extension with parser tests — both still
  owed; independent review (CLEARED) of the frozen revision;
  bootstrap seed and k list recorded at freeze; **freeze is the
  owner's act**, naming the first counted slate. None is requested
  by this design.
- **Until then:** family state DESIGN ONLY; counted rows zero by
  construction.

## 9. Honest readiness verdict

**VIABLE TO SCREEN.** The mechanism under test (state-conditioned
drive dynamics) is the one the failure record itself names, it is
absent from both failed predecessors by construction rather than
by degree, and the screen's added Q4 leg means the construction
must win where its claim lives or fail. The bar is honestly high —
B0's static shares already average the very dynamics being modeled
(§6.1) — and a failure here closes the state-conditioned direction,
leaving the family DESIGN ONLY until a new input class (e.g.
captured DK period lines deep enough to screen against prices
rather than model baselines) exists.

**What would falsify this design (before any screen):** a build
finding that the §3.2 state functions, estimated on training
seasons, are not stable across 2023 vs 2024 vs 2025 at league level
(state behavior itself drifting faster than the window) — reported
as a design-stage falsification, not patched with per-season fits.

## 10. Path from this draft (checklist)

- [ ] Independent review of this design by a checker who did not
      draft it.
- [ ] Build the simulator + panel reproduction (§6.5's guard) with
      §7 readings recorded; screen per §5; verdict committed.
- [ ] If SCREEN_FAIL: stop. Construction retired.
- [ ] If SCREEN_PASS: family-path steps 1–2 (capture expansion,
      intake grammar) land; the forward draft is revised to name
      this construction (§8); review; owner freeze requested.
      **None of that is requested here.**
