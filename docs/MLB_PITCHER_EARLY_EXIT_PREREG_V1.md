# MLB Pitcher Early-Exit Component V1 — Preregistration (Case Check)

**Status: FROZEN before any scoring. Research only. Zero card pricing impact.
This component is NOT wired into any runner, card path, or the frozen forward
protocol. It creates no PLAY eligibility and changes no existing engine tail.**

## 1. Purpose

The pitcher-K engine's tails carry no mass on early starter exits (a standing
caveat on the record since Oct 15, 2026). Two of the four graded units in the
frozen pitcher-K forward protocol
(`config/research/mlb_pitcher_k_forward_validation_v1.json`) lost on exactly
that failure mode — one hook, one leash. This preregistration freezes a
research component that re-tails a pitcher's strikeout distribution through
an explicit starter-exit mixture, and a two-case check of that component
against the existing engine tails on those two graded losses.

**This is a CASE CHECK on n = 2, explicitly NOT validation.** Section 9
states what promotion would still require.

## 2. The graded cases (cited from the graded records)

Both cases are the same game: **NLCS Game 4, Milwaukee Brewers @ Los Angeles
Dodgers, Thu Oct 15, 2026 (gamePk 849810), final MIL 6, LAD 4.**

### Case A — Unit #3, Tyler Glasnow (HOOK)

- Pitcher: Tyler Glasnow (LAD, MLBAM 607192), starting pitcher.
- Unit: K **OVER 6.5 @ +105** (paired two-sided main: Over +105 / Under −134),
  captured 4:18 PM CT pregame on run 1 of `operative_run_20261015_evening`;
  model p (over) **.808** vs de-vigged market .460; status
  `RESEARCH_CANDIDATE_NOT_VALIDATED`.
- Realized: **6 K → LOSS (−1.00u)**.
- Final line (grade record; MLB StatsAPI boxscore for gamePk 849810 agrees
  exactly): **4.1 IP = 13 outs, 3 H, 4 ER, 2 BB, 6 K, 79 pitches.**
- Failure mode: **HOOK** — a deep-start distribution truncated by a
  performance-driven early exit (4 ER; the grade record's hypothesis note:
  "the .808/.808 pair priced a deep-start distribution that a 79-pitch, 4-ER
  outing truncated").
- Records: `operative_run_20261015_evening/GRADE_AND_REVIEW_RERUN.md`
  (unit #3 section), corroborated in
  `operative_run_20261015_night/GRADE_AND_REVIEW.md`.

### Case B — Unit #4, Shane Drohan (LEASH)

- Pitcher: Shane Drohan (MIL, MLBAM 675660), starting pitcher (opener).
- Unit: K **OVER 2.5 @ +106** (paired two-sided main: Over +106 / Under −135),
  captured 18:35 CT pre-first-pitch on the `operative_run_20261015_night`
  card; model p (over) **.808** vs de-vigged market .458; status
  `RESEARCH_CANDIDATE_NOT_VALIDATED`.
- Realized: **1 K → LOSS (−1.00u)**.
- Final line (grade record; MLB StatsAPI boxscore agrees exactly):
  **1.0 IP = 3 outs, 1 H, 1 ER, 2 BB, 1 K, 25 pitches.**
- Failure mode: **LEASH** — priced off a 12-prior-start distribution, but
  Milwaukee used him as a one-inning opener in a bullpen game (grade record:
  "K/Outs/HA overs are leash-length bets before they are stuff bets";
  "relieved after the 1st").
- Record: `operative_run_20261015_night/GRADE_AND_REVIEW.md` (unit #4
  section).

### Explicitly excluded

- **Unit #5, Nick Martinez K OVER 2.5 @ +133 — VOID by owner ruling**
  (PR #2374; `operative_run_20261016/UNIT5_VOID_RECORD.md`). It is a record,
  not a graded loss. It is **not scored** in this case check.
- Units #1 (Williams, W) and #2 (Jax, L) are not early-exit cases and are
  not scored here. The graded records themselves are preserved untouched.

## 3. The existing engine tails (comparison distribution)

- Engine: `sportsedge/pitcher_joint_engine.py`, `ENGINE_VERSION =
  mlb_pitcher_joint_empirical_bayes_v4_long_window_prior`. For PITCHER_K
  with no adjustment lane, pricing is the empirical distribution of the
  pitcher's strictly-prior starts plus a Jeffreys Dirichlet (α = 0.5 per
  settlement category) posterior (`sportsedge/mlb_empirical_bayes.py`). For a
  half line L with n pool starts and uniform weights:

      p_over(L) = (0.5 + #{pool starts with K > L}) / (n + 1)

- **Pool reconstruction (declared):** each case pitcher's pool is his **12
  most recent games started (gamesStarted = 1) strictly before 2026-10-15**,
  from MLB StatsAPI gameLog (season 2026, group pitching) — the source the
  cards themselves record (`FREE_MLB_STATSAPI_GAMELOG`,
  `prior_start_count` 12 for both pitchers).
- **Fingerprint gate (must pass before scoring; on any mismatch, STOP and
  report — do not score):** the reconstructed pools must reproduce, via
  p = (0.5 + count) / 13, all nine model probabilities recorded on the
  Oct 15 cards:

  | Pitcher | Recorded row | Recorded p | Required count of 12 |
  |---|---|---|---|
  | Glasnow | K over 6.5 | .808 | #{K ≥ 7} = 10 |
  | Glasnow | Outs over 14.5 | .808 | #{outs ≥ 15} = 10 |
  | Glasnow | BB under 2.5 | .731 | #{BB ≤ 2} = 9 |
  | Glasnow | Hits allowed under 3.5 | .577 | #{H ≤ 3} = 7 |
  | Glasnow | ER over 1.5 | .654 | #{ER ≥ 2} = 8 |
  | Drohan | K over 2.5 | .8077 | #{K ≥ 3} = 10 |
  | Drohan | Outs over 7.5 | .962 | #{outs ≥ 8} = 12 |
  | Drohan | Hits allowed over 2.5 | .962 | #{H ≥ 3} = 12 |
  | Drohan | ER over 0.5 | .962 | #{ER ≥ 1} = 12 |

- **Implied existing pmf (declared definition):** with n = 12 and
  Kmax = max K in the pool, the existing tails are the unique distribution
  whose half-line survival function equals the engine's quoted p_over at
  every half line 0.5 … Kmax + 0.5:

      q(k) = #{pool starts with K = k} / (n + 1)      for 1 ≤ k ≤ Kmax
      q(0) = (#{K = 0} + 0.5) / (n + 1)
      q(Kmax + 1) = 0.5 / (n + 1)
      q(k) = 0 elsewhere

  (The two Jeffreys half-masses sit at the feasible boundary atoms 0 and
  Kmax + 1. Interior values with no prior start carry zero mass — that is a
  real property of the existing tails, and §8 handles it openly.)

## 4. Historical construction data (component)

- Source: MLB StatsAPI (`statsapi.mlb.com`), free and public; fetched once
  and cached with sha256 recorded in the case-check record.
- Enumeration: season pitching stats (sportId 1, gameType R, playerPool ALL)
  → every pitcher with gamesStarted ≥ 1 in the season; then that pitcher's
  gameLog (group pitching) for the season.
- Seasons and declared regular-season windows (completed seasons only):
  **2023: 2023-03-30 .. 2023-10-01 · 2024: 2024-03-20 .. 2024-09-29 ·
  2025: 2025-03-18 .. 2025-09-28.** A row counts as a start iff
  gamesStarted = 1 and its date is inside the season's window.
- Per start: total outs O (inningsPitched converted: outs = 3·whole +
  partial, where "4.1" = 13), runs allowed R, pitches P (numberOfPitches),
  strikeouts K.
- Missing-data rule: a start with numberOfPitches missing cannot be LEASH
  (§5 ordering); it is still counted for HOOK/NORMAL by R. The count of such
  starts is reported; if it exceeds 1% of starts, that is reported
  prominently in the record.

## 5. Scenario construction (frozen)

Each historical start is assigned exactly one state, in this order:

- **HOOK** if R ≥ 5 (performance blow-up proxy for a hook game);
- else **LEASH** if P ≤ 65 (short-leash / opener-economy proxy);
- else **NORMAL**.

Frozen quantities, all computed from the §4 pool only:

- Weights: `w_s = #{starts in state s} / #{all starts}`, s ∈ {HOOK, LEASH,
  NORMAL}.
- Exit distribution per state: `P̂_s(O = o)` = empirical frequency of total
  outs o ∈ {0, …, 27} among starts in state s.
- Exit band: completed innings `C = floor(O / 3)` ∈ {0, …, 9}. Realized
  bands: Glasnow O = 13 → **C = 4**; Drohan O = 3 → **C = 1**.
- League strikeout rate: `λ_lg = (Σ K) / (Σ O)` over all historical starts.

No parameter above is estimated from, or adjusted after seeing, the two
graded cases. The thresholds (R ≥ 5, P ≤ 65) are declared here, before
scoring.

## 6. Component (frozen)

For a target pitcher, let his §3 pool give `λ = (Σ pool K) / (Σ pool outs)`
(his own strikeout rate per out). The component distribution is

    P_comp(K = k) = Σ_s w_s · Σ_o P̂_s(O = o) · Poisson(k; λ·o),
    Poisson(k; 0) := 1{k = 0},   k = 0 … 80

(mass beyond k = 80 is < 1e-12 for any λ in scope; total mass is checked to
equal 1 within 1e-9 in code).

The mixture exit distribution is `P_mix(C = c) = Σ_s w_s · P̂_s(C = c)`.
Declared identity: because the states partition all starts and the weights
are their frequencies, P_mix over outs equals the pooled empirical outs
distribution of §4. The component's content is the per-state exit
decomposition (hook vs leash vs normal) combined with the pitcher's own
K-rate re-tailing — not a different marginal exit curve.

## 7. Sanity checks (frozen; reported regardless of outcome)

- (a) **Nonzero early-exit mass:** `P̂_HOOK(C ∈ {1,2,3,4}) > 0` and
  `P̂_LEASH(C ∈ {1,2,3,4}) > 0`.
- (b) **League-profile band check:** `P_mix(C ∈ {1,2,3,4})` must lie within
  ±0.05 of the historical pooled empirical `P(C ∈ {1,2,3,4})`. By the §6
  identity they are equal; this is a code-correctness check.
- (c) The per-band masses `P̂_HOOK(C = c)` and `P̂_LEASH(C = c)` for
  c = 1, 2, 3, 4 are reported in full in the record, for a league-average
  starter profile as well as for each case pitcher (the exit masses do not
  depend on λ; the K distribution does).

## 8. Scoring bar (frozen; not to be lowered)

For each case, with realized strikeouts K* (Glasnow 6, Drohan 1):

- existing log score `ln q(K*)`; component log score `ln P_comp(K*)`. If a
  distribution assigns zero mass to the realized K, its log score is
  **−∞ and is reported as −∞** — no epsilon substitution, no smoothing
  after the fact.
- component exit-band mass at the realized band, `P_mix(C = C*)`.

**CASE_CHECK_PASS** iff

    [ln P_comp(6) + ln P_comp(1)]  >  [ln q(6) + ln q(1)]
    AND  P_mix(C = 4) > 0  AND  P_mix(C = 1) > 0.

Otherwise **CASE_CHECK_FAIL**, with all numbers reported either way.

Secondary, descriptive only (never moves the verdict): CRPS of each
distribution against the realized K for each case.

## 9. What this is not

- n = 2, and the two cases are the very losses that motivated the component.
  A pass is an anecdote consistent with the design intent, not evidence.
- Nothing here touches the frozen forward protocol
  (`config/research/mlb_pitcher_k_forward_validation_v1.json`), the
  existing engine, any graded record, or any card. Protocol state remains
  5 recorded / 4 graded (1–3, −2.06u) with unit #5 VOID.
- Promotion of any early-exit tail into pricing would still require
  chronological out-of-sample improvement over **both** the existing model
  **and** a market baseline across that protocol's ≥150 graded prospective
  units. This case check creates no such claim and no PLAY eligibility.

## 10. Deliverables of the build (in order)

1. This preregistration, committed alone, before any scoring code runs.
2. The component as a standalone research module (no imports from, or
   changes to, any runner/card path).
3. A scoring script that re-verifies the §3 fingerprint gate, builds the
   §4–§6 quantities, and emits a results JSON.
4. A case-check record (validation-style document) carrying this
   preregistration's sha256, the data cache hashes, all §7–§8 numbers, and
   the verdict — recorded whichever way it comes out.
