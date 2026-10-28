# DESIGN — MLB Game Lines Successor Construction

**Construction ID (proposed):** `MLB_GAME_STATE_V1` (short: GS_V1)
**Markets:** MLB moneyline, game total, and team totals — the outputs of one
joint run distribution, as in the retired construction's surface. Run line
and the derived game-prop markets (exact score, race-to-X) stay gated
behind this family's validation, per the taxonomy record (PR #2837);
nothing in this design opens them.
**Status: DESIGN ONLY.** This document is not a preregistration, not a
freeze, not code. Nothing in it prices a card, opens a clock, starts a
count, or changes any ruling. `MLB_GAME_DIST_V1` stays **FAILED-CLOSED at
both fidelities** (reduced fidelity, PR #2833; full fidelity, PR #2857) —
retired, never resurrected, and its folds are design data for this
document, never a tuning set for the successor. Cards show NO_ENGINE for
MLB game lines until a construction validates under the program's verified
definition.
**Date:** Wed Oct 28, 2026 · **Author:** Rocky (Muse), under Isaac's
directives of Oct 26–28, 2026 ("Get verified engines. Everywhere.";
"All models today parallel... Everything") and the gap-fill plan's MLB
ordering (game lines last; the sport's validated weight sits on pitcher
props and batter props meanwhile).

---

## 1. The failure record this design must answer

### 1.1 What failed, at both fidelities

`MLB_GAME_DIST_V1`: team season-window OFF/PIT run rates (PIT at team
level in the reduced run; decomposed per §2.2 of its design into
`exp_inn_S × starter_rate9_S + (9 − exp_inn_S) × bullpen_rate9` in the
full run) → run means λ → joint negative-binomial grid → moneyline /
totals / team-total probabilities. Walk-forward folds fit ≤2022→2023,
≤2023→2024, ≤2024→2025, ≤2025→2026; test n = 9,718 (full-fidelity run,
fresh StatsAPI pull of 14,577 games, 2021–2026, sha256-pinned manifest):

| Metric (pooled) | Reduced | Full fidelity | Base rate | Elo | League avg |
|---|---|---|---|---|---|
| ML Brier ↓ | 0.2546 | **0.2567** | 0.2492 | 0.2487 | — |
| ML log loss ↓ | 0.7026 | **0.7070** | 0.6916 | 0.6912 | — |
| Total MAE ↓ | 3.641 | **3.685** | — | — | 3.558 |
| Team-total MAE ↓ | 2.554 | **2.580** | — | — | 2.513 |

FAIL on every leg of its own §3.1, pooled and in every fold. The
full-fidelity decomposition made every metric **worse** than the reduced
replica on identical data (ΔBrier +0.0021, Δlog loss +0.0044, Δtotal MAE
+0.044, Δteam-total MAE +0.026). Calibration signature, both fidelities:
stated probabilities span **0.391–0.640** across deciles while realized
home win rates stay inside **0.509–0.570** — spread manufactured by the
model that the outcomes never confirm.

### 1.2 The three structural defects, named

1. **Information starvation (the primary defect).** V1's inputs were
   season-window team aggregates. A single game's run expectation is
   moved by state those aggregates cannot see: tonight's actual batting
   order and its platoon matchups, which relievers are actually available
   tonight, the home-plate umpire, and the weather at first pitch. V1 had
   none of these. It redistributed one season-level information set into
   per-game probability spread — the calibration table is what that looks
   like when graded.
2. **Granularity without information.** The §2.2 decomposition split PIT
   by tonight's starter *identity* while feeding the split the same class
   of information (prior run rates). The split injected identity variance
   at shrinkage weights the outcomes did not reward. The lesson is not
   "decomposition is wrong"; it is that **finer structure only helps when
   it carries new information** — a split driven by *state* (who can
   actually pitch tonight, in what order the lineup actually bats) is a
   different claim from a split driven by relabeling the same rates.
3. **A pass bar with no market leg and no calibration gate.** Phase D
   graded against base rate, Elo, and league averages only, because no
   timestamped market archive exists (Gap G4) — and V1 lost to even those
   baselines, so the missing market leg is not what killed it. But a
   successor protocol that repeats the same baseline set invites a
   construction that squeaks past naive baselines while carrying no
   plausible edge. Calibration was *reported* in Phase D but was not a
   pass/fail gate; a successor can therefore "pass" on MAE/Brier while
   still manufacturing probability spread. Both holes are closed in §5 of
   this design, in advance.

A fourth point is governance, and V1 got it right: strictly-prior
histories, the watermark assertion, the truncation audit, the
unknown-prior rule for starters with < 3 prior starts, and one
configuration run with declared shrinkage constants. Those are adopted
here as program machinery (§4.4), not re-invented.

---

## 2. The claim, stated in two sentences

**A single MLB game is priced by tonight's personnel and environment
state — the actual lineup's platoon profile against the actual starter,
the bullpen's availability-weighted quality after recent workload, the
home-plate umpire, and first-pitch weather — and a construction that
conditions its run distributions on that state, with calibration fitted
as part of the construction on fit windows only, will beat the base rate,
a plain Elo, and league-average baselines on walk-forward outcomes, and
will not lose to the market proxy on the one fold where a lawful proxy
exists. If it cannot do those things, the state information is not an
edge either, and this family's honest record is NO VIABLE CONSTRUCTION
until the forward clock — not another design — is the only test left.**

Why this is a different claim from V1's, not a re-skin: V1 claimed
season-level team quality differences, expressed through rates, price
single games. Every variable in this claim is *game-specific state* that
is (a) knowable before first pitch in forward operation, (b) absent from
V1's information set entirely, and (c) not derivable from V1's outputs.
The model class changes too (§4.2), but the design's bet is placed on the
information, where §1.2 says the failure lived.

---

## 3. Inputs — what is new, and each one's admission status

| # | Input (new information) | What it adds over V1 | Historical source (screen) | Admission status | Forward source (clock) |
|---|---|---|---|---|---|
| 1 | **Tonight's lineup + platoon splits** — the 9-man order as played; each batter's shrunk runs/PA vs LHP and vs RHP; lineup-weighted offense vs the opposing starter's hand and the bullpen tiers behind him | V1's OFF was one team rate against all pitching. Platoon advantage is the largest per-game offensive swing a lineup card creates, and it is invisible to a season aggregate | **Retrosheet event files** — PA-level records (the pinned park-factor derivation already parses them at PA level). Actual-lineup substitution declared, §4.4 | **PARTIALLY PINNED.** 2022–2024 event zips hash-pinned (PR #2856, re-derivation MATCH) — but that pin's scope is park-factor derivation. Using the same bytes for PA/lineup features needs a **scope-extension admission** + the 2025 zip pin (step A, §6) | MLB StatsAPI live feed lineups — **NOT ADMITTED**; admission is a pre-clock obligation (§6), not a screen blocker |
| 2 | **Bullpen availability state** — per team: the quality of relievers actually available tonight, weighted down by trailing-3-day pitches/appearances; replaces V1's season bullpen rate with an availability-weighted bullpen term | V1's bullpen term was a season rate: it priced a rested closer and a closer on his third straight day identically. Availability is state, not identity | **MLB StatsAPI boxscore pitching logs** — the same pull that built the Phase D dataset (14,577 games, manifest sha256-pinned on main) | **ADMITTED SUBSTRATE.** StatsAPI is the program's MLB research substrate (Phase D dataset + manifest in-repo); availability is a feature layer on it, defined and frozen at build (§4.1) | Same StatsAPI pull, daily — already the program's substrate |
| 3 | **Home-plate umpire + tendency** — umpire identity; shrunk run-environment / called-strike tendency from strictly-prior games behind the plate; bounded totals-primary term | V1 had no umpire term at all. The effect is small and real in the literature of the game; the design bounds it and makes it earn its place by ablation (§5.3) | Retrosheet event-file game-info records carry umpire assignments — **this must be verified on the pinned bytes before build** (step A, §6); if the pinned zips do not carry usable umpire records, this class descopes pre-declared (§7), it is never sourced from a scrape of convenience | **NOT ADMITTED** as a modeling input (the pitcher-props extension design, PR #2839, names umpire tendency as a bounded term — a design mention, not an admission). Admission path = the same scope-extension record as #1, with the byte-verification step | StatsAPI live feed officials — **NOT ADMITTED**; pre-clock obligation (§6) |
| 4 | **Weather at first pitch** — temperature, wind speed/direction vs park orientation, precipitation; roof state for retractable parks | V1 applied park factors but no game-day environment. Wind/temperature move totals materially game-to-game | **Open-Meteo Previous Runs API** — lead-time-labelled past forecasts (`previous_day1`: available no later than valid_time − 24h). The in-tree module (`sportsedge/open_meteo_previous_runs.py`) exists precisely because the regular forecast API leaks in backtests; its records state `availability = LEAD_TIME_BOUND` and never claim exact issue times. **Observed actuals are never a screen input** — a pre-game model graded on observed weather is graded on information it cannot have | **IN-TREE, NOT ADMITTED for this use.** The module is research-only on its face ("never a pricing input without separate review"); the screen pull needs a **pin record** (step B, §6). The card lane's archived-evidence contract (`SPORTSEDGE_WEATHER_EVIDENCE_V1`) governs card use, not this screen | NWS / Open-Meteo live modules in-tree (`nws_weather_source.py`, `mlb_weather_roof_source.py`) — the forward runner snapshots the forecast at pricing time under the same evidence contract |
| 5 | **Component park factors** (carried from V1, provenance now stronger) | — | Retrosheet 2022–2024, derivation in-repo | **PINNED + RE-DERIVATION MATCH** (PR #2856: all 180 component cells reproduce byte-identically). Carried folds use this table; the two 2025 relocations (Athletics–Sacramento, Tampa Bay–Steinbrenner) are flagged rows with a declared treatment at build, not silently priced on Oakland/Tropicana factors | Same table until a governed refresh pin |
| 6 | **Starter rate + expected innings** (carried from V1 §2.2) | — | StatsAPI pitching logs (Phase D substrate) | Admitted substrate, as #2. The unknown-prior rule (< 3 prior starts → league prior) carries verbatim | StatsAPI probable pitchers (the prepricing stage already hydrates them from the schedule endpoint) |

**Explicitly excluded inputs, with reasons:**

- **Pitch-level / Statcast features via pybaseball** — pybaseball is an
  *undeclared dependency* (confirmed live defect, PR #2855: imported by
  `scripts/refresh_statcast_daily.py`, declared in no manifest). Not
  admitted; may be proposed later as its own admission after the
  both-manifests fix lands. The construction must not depend on it.
- **Market data as a feature** — rejected method under program law (noted
  once in the prepricing contract; repeated here so there is no
  ambiguity). Lines appear in this design only as grading baselines.
- **OddsPortal-sourced anything** — standing ToS exclusion (the gap hunt
  rejected its MLB file on exactly this ground).
- **Anything paid** — free-only law. The timestamped historical odds
  endpoints documented in the gap hunt are paid; they are not an
  admission path, they are a closed door (Gap G4 stays open, §6).

---

## 4. Construction spec

### 4.1 Run-mean construction (state-conditioned, PA-component)

For team T batting against opponent O in park P:

1. **Lineup offense.** For each of T's nine lineup slots, the batter's
   shrunk run value per PA split by pitcher hand (vs LHP / vs RHP),
   fitted on strictly-prior PA history with shrinkage declared at build.
   Slot PA shares come from the lineup position (league slot-share table
   fitted on the fit window).
2. **Pitching faced, in phases.** The starter phase (expected innings
   from the §2.2-carried estimator) is priced against the starter's
   shrunk rate *and* the lineup's platoon profile against his hand. The
   bullpen phase is priced against O's **availability-weighted bullpen**:
   relievers weighted by a declared availability function of trailing-3-
   day pitches and appearances (a reliever over the declared workload
   threshold contributes at the next-man-up tier rate, not his own). The
   availability function's form and thresholds are declared a priori in
   the build record — one configuration, as in V1's governance.
3. **Context terms (bounded, totals-primary).** Park component factors
   (pinned table); weather term from the forecast snapshot (temperature
   + wind component vs park orientation + precipitation), fitted on fit
   windows; umpire term (home-plate umpire's shrunk run-environment
   tendency), bounded to a declared cap. Each context term is separately
   ablatable (§5.3).
4. **Run means.** λ_T and λ_O from the components above — the means are
   the *only* place state enters; no term touches a price.

### 4.2 Distribution and probability map (where V1's map defect is answered)

- Run totals: negative-binomial marginals with dispersion fitted per
  fold on the fit window (the NB family is a distribution shape, not
  V1's failed claim; what failed was its λ's and its map — both replaced
  here).
- **Win probability is NOT read off raw λ differences.** A calibration
  layer — logistic on (λ differential, λ total, home indicator) — is
  fitted **on the fit window only**, walk-forward, and is part of the
  construction: stated probabilities are the calibrated layer's outputs.
  V1's signature (stated spread 0.391–0.640 vs realized 0.509–0.570) is
  precisely what an unfitted map produces; here the map is fitted where
  fitting is legal and gated where it is graded (§5.2, criterion 3).
- Totals / team-total probabilities read off the calibrated joint
  distribution; the joint's correlation treatment is declared at build
  (V1 fitted r per fold; the successor declares its treatment a priori
  and holds it across folds).

### 4.3 Selection

None at design stage. If the construction ever freezes, program law
applies unchanged (+3% EV headline floor, −165 cap, ≥ +40% EV to the
overconfidence bucket, LEAN labeling) — stated here so the design cannot
be read as smuggling a selection rule past the card gates.

### 4.4 Point-in-time discipline (adopted from V1's audit, verbatim in effect)

- Histories update only after the game they describe is scored;
  watermark assertion in code; a truncation re-run must reproduce a
  fold's predictions bit-identically (V1's audit passed all four checks;
  the standard is kept, not lowered).
- **Declared substitution, on the record as V1 §2.3 was for starters:**
  the screen scores the lineup *as played* (Retrosheet) and the umpire
  *as assigned*. In forward operation both are known before first pitch
  (lineups post hours ahead; the runner snapshots them at pricing time).
  The known bias class — late lineup scratches, which the backtest
  cannot see and the forward runner can — is named here and must be
  graded as a disclosed row class on the forward clock, never buried.
- Weather enters only as the lead-time-labelled forecast (input #4).
  Any feature found to consume post-first-pitch information voids the
  screen run that used it.

---

## 5. Design-screen protocol (cannot repeat V1's baseline mistake)

### 5.1 Windows and data

- **Primary folds mirror V1 exactly** — fit ≤2022→2023, ≤2023→2024,
  ≤2024→2025 — so every number is directly comparable to the record in
  §1.1. The 2026 fold is excluded until Retrosheet 2026 events are
  pinned (a named admission step, not an oversight).
- Primary data: StatsAPI history (Phase D substrate, re-pulled fresh at
  build with a new manifest pin) + Retrosheet PA/lineup/umpire features
  (step A pins) + Previous Runs weather (step B pin).
- **Market-proxy leg (2025 fold only):** the `minmaxxxer/mlb-closing-odds-2025`
  consensus file (Hugging Face, CC BY 4.0; every 2025 game, consensus
  open/close, date-only, no book) — pinned by hash at build and labeled
  **DESIGN-GRADE MARKET PROXY** everywhere it appears. It is not a
  timestamped archive, it does not close Gap G4, and no CLV claim may be
  drawn from it. An auxiliary older window (fit ≤2018 → 2019–2021 vs the
  SBR-family date-only closes the gap hunt pulled, §4.1 of PR #2850) may
  be reported as supporting evidence, labeled the same way; it is not a
  pass/fail surface.

### 5.2 Pass criteria — all required, stated in advance

1. **Naive bars, every fold.** ML Brier AND log loss beat the home base
   rate AND the simple Elo (same baseline spec as V1's Phase D) pooled
   AND in every primary fold. Totals MAE AND team-total MAE beat the
   league-average baselines pooled AND in every primary fold. (This is
   the bar V1 failed. It is kept, verbatim in effect.)
2. **State-information control.** The full construction must beat, on
   pooled Brier, a **V1-shaped control run on identical folds and data**
   (season-rate λ's, no state inputs, same calibration layer) — the
   direct test that the new *information*, not the refit or the
   calibration layer, earns any pass. If the control matches the full
   model, the state claim is falsified on the spot.
3. **Calibration gate.** No stated-probability decile with n ≥ 200 may
   deviate from its realized rate by more than 7.5 pp (the program's
   standing band tolerance), and the calibration layer fitted on fit
   windows must not require refitting on any test fold to hold the gate.
4. **Market-proxy leg.** On the 2025 fold, ML Brier must beat the
   consensus close's Brier on the same games (log loss reported
   alongside). A construction that cannot beat a date-only consensus
   close on the one fold where the comparison lawfully exists has no
   plausible forward edge, whatever the naive bars say — this leg exists
   so a PASS cannot be a weak-baseline artifact.
5. **No tuning.** One configuration; shrinkage weights, the availability
   function, and all caps declared a priori in the build record. A
   changed constant is a new version with its own design pass. The
   screen's folds are design data for any such version, never a tuning
   set — the exact rule V1's Phase D record closed with.

### 5.3 Ablation reporting (required output, not a pass gate)

The screen report must print the full model and each single-class
ablation (lineup/platoon off; availability off; umpire off; weather
off). A class whose removal does not hurt pooled Brier beyond its
bootstrap interval is **dropped from the freeze candidate** — the
anti-decomposition rule learned from §1.2 defect 2: structure that does
not carry information does not ship.

---

## 6. The forward reality — Gap G4 and the 2027 clock (armed, not idle)

**G4 stands.** No timestamped MLB game-line archive exists free (gap
hunt, PR #2850: the free surface is date-only SBR-family files and one
2025 consensus file; the only timestamped route is paid, and paid is
closed by the free-only law). Therefore:

- The §5 screen is **accuracy evidence + one design-grade market-proxy
  leg**. It can kill this construction; it cannot verify it. No screen
  outcome, however strong, makes a verified claim.
- **Verification is forward-only**, under the standing definition
  (repeal form, Oct 27, 2026): pass chronological out-of-sample
  validation against BOTH the existing model (the Lane A cold model, for
  this family) and a contemporaneous market baseline — which for MLB
  game lines can only be the lane's own DraftKings captures.

**Clock design (so the family is armed when the season opens):**

- **Capture basis:** the lines lane's DK captures under the standing
  two-mark cadence (T-1H write + FINAL write per game, five-timestamp
  delivery receipts), including the NRFI/YRFI labeling rule for the
  1st-inning O/U 0.5 market (owner's Oct 26, 2026 rule; label applied by
  the program, DK shows none).
- **First counted slate:** the **2027 Opening Day** slate priced by the
  frozen construction — the "2027 Opening Day forward clock plan" the
  gap hunt left unchanged. No backfill; counting starts at zero.
- **Preconditions, all named, all before Opening Day:** (i) §5 screen
  PASS on the exact build; (ii) freeze as its own prospective act —
  independent review closed on the exact head before the freeze is
  recorded, owner authorization, named first slate (the V2 sequencing
  law); (iii) the **StatsAPI live-feed admission** (lineups + officials)
  landed, since the forward runner's state inputs ride it; (iv) the
  evaluator pinned by amendment before any metric is computed (the NFL
  team-totals precedent). If any precondition is unmet at Opening Day,
  the first counted slate slides to the first slate after all four hold
  — the clock never starts on a partial basis.
- **Verdict mechanics on the clock:** CLV against the captured DK close
  reported first; the v1.1-style close rule applied by analogy declared
  in the future prereg; the multiple-testing divisor k recomputed at
  verdict date; late-scratch rows graded as their own disclosed class
  (§4.4).
- **Admission steps owed before the screen build (small, governed):**
  **Step A** — Retrosheet scope extension: verify on the pinned bytes
  that the event files carry usable PA, lineup, and umpire records; pin
  the 2025 event zip by the #2856 pattern; record the extension.
  **Step B** — Previous Runs weather pin for the screen window (pull
  once, hash-pin, record the LEAD_TIME_BOUND availability honestly).
  Neither step requires a new source, a payment, or an account.

---

## 7. Risks and falsifiers

- **The state variables may simply be priced or noise.** Lineup platoon
  and bullpen workload are public and old; the market and Elo may
  already carry them. Falsifier: §5.2 criteria 1–2 — if the control run
  matches the full model, the information claim is dead and the record
  should say so.
- **Umpire tendency may be unstable** across seasons (assignments and
  zones drift; the automated zone era is coming). Mitigation: bounded
  term, ablation (§5.3), and the pre-declared descope — if step A's
  byte verification fails OR the ablation shows the class carries
  nothing, the class is dropped by rule, not by judgment call.
- **Weather forecast error** is irreducible; the screen grades the model
  on the forecast it would actually have had (lead-time-labelled), so
  the error is inside the measurement, not hidden by it.
- **Retrosheet revision drift:** Retrosheet revises event files (its
  Summer 2026 release updated 14,631 games). The zip-level hash pins
  make any revision visible before it can move a feature — the same
  protection the park-factor pin established.
- **Single-fold market leg.** The proxy leg is one fold, one consensus
  source, date-only. It is a necessary condition, not sufficient
  evidence; the design states this so nobody — including a future
  reader of a PASS — mistakes it for a market validation.
- **Collapse condition, declared in advance:** if step A finds the
  pinned Retrosheet bytes cannot support lineup reconstruction at PA
  level, the construction's primary input does not exist on admissible
  data, and this design's verdict collapses to **NO_VIABLE_SUCCESSOR
  until a PA-level source is admitted** — recorded as such, with the
  2027 clock plan reverting to capture-only accrual (lines captured and
  graded against the cold model as diagnostics, no construction clock).

---

## 8. Why this is not a resurrection of MLB_GAME_DIST_V1

| Dimension | MLB_GAME_DIST_V1 (FAILED-CLOSED) | MLB_GAME_STATE_V1 (this design) |
|---|---|---|
| Information set | Season-window team OFF/PIT aggregates only | Tonight's state: lineup/platoon, bullpen availability, umpire, first-pitch weather forecast + carried park/starter components |
| Pitching term | Team rate, then starter/bullpen split of the *same* rates (hurt every metric) | Availability-weighted bullpen (state, not identity); starter priced against the actual lineup's platoon profile |
| Probability map | Raw λ differences through the NB grid, unfitted (stated 0.391–0.640 vs realized 0.509–0.570) | Calibration layer fitted on fit windows only, part of the construction, gated as a pass criterion |
| Screen baselines | Base rate, Elo, league averages — and it lost to them | The same naive bars (kept) + a V1-shaped control on identical folds + a calibration gate + a design-grade market-proxy leg |
| Market relationship | None available (G4); accuracy-only by necessity | Still G4-bound; proxy leg labeled design-grade; verification reserved to the 2027 DK-capture forward clock |
| Failure handling | Closed by its own §3.1 at both fidelities | Pre-declared descope (umpire) and collapse condition (§7); one configuration, no tuning |

Shared elements are governance, not construction: strictly-prior
discipline, the watermark/truncation audit, the unknown-prior starter
rule, and the program's card gates — the machinery every family runs
under.

---

## 9. Honest readiness verdict

**DESIGN ONLY — VIABLE TO SCREEN, gated on two small admission steps
(§6, steps A–B), with the forward-feed admission (§6 precondition iii)
gating the 2027 clock rather than the screen.**

The screen can run on data that is already pinned (StatsAPI history,
Retrosheet 2022–2024) plus two mechanical pin extensions, against a
protocol that keeps every bar V1 failed and adds the three gates V1's
record shows were missing (state-information control, calibration,
market proxy). What the screen cannot do — what no historical screen
can do for this family while G4 stands — is verify. The 2027 clock is
therefore designed now, with its preconditions named, so that a screen
PASS converts into an armed forward test on Opening Day instead of a
document idle until April.

**Recommended next step (Rocky's clearance / owner's call):** execute
admission steps A and B as one governed pin PR; then build the
construction + control + screen exactly as §5 specifies and run it. If
the screen fails, the failure record closes this family on current
inputs with the same finality as V1's — and the program's MLB weight
stays where it already sits: pitcher props, batter props, and the
capture lane accruing the only baseline that can ever verify a game-line
construction.
