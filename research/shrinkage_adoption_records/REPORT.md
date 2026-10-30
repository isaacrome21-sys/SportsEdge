# Model Fix Lane — Consolidated Report

**Directive:** Isaac, Oct 14 2026, 9:51 PM CT: "Daily models get
fix — Failed." **What this lane did:** each failed daily model
was answered with a CHALLENGER built under a new preregistration
— never an in-place edit. Production code, registry, and
thresholds are untouched everywhere (Child B verified zero repo
diffs; Children A/C worked evaluator-side against the read-only
clone). **Label of everything here: RESEARCH_EVIDENCE** —
retrospective calibration evidence on declared untouched splits.
Nothing is a market verdict; nothing here adopts anything.
Adoption candidacy means a challenger beat the frozen engine AND
both naive baselines with paired CIs entirely < 0; each
ADOPT-CANDIDATE below is a **recommendation to Isaac only**,
sequenced after the M2/M4 market verdicts publish (separate
lane).

**Frozen evaluand:** origin/main `2a713380c` — all nine evaluand
files verified byte-identical to the Phase 2 evaluand at
`12999fc22` (per-file hashes in the results JSONs).

**Method common to all families:** preregistration written and
SHA-256-locked before any challenger scoring (specs/ +
SPEC_HASHES.txt); construction constants fixed in the prereg from
the Phase 2 measured defect, never tuned on the test split;
design/diagnosis data (Phase 2) and test data disjoint
chronologically; arms FROZEN / CHALLENGER / B1 / B2 scored on
identical fixture sets; paired CIs by ISO-week block bootstrap,
2,000 resamples, seed 20261015; Phase 2 parity batteries passed
before scoring in every family; determinism verified by full
re-runs (byte-identical except timestamps) in every family.

## Lane-level records and flags

1. **Spec-hash record defect (coordinator's error, caught by the
   lane's own discipline).** The batter-props token recorded in
   `SPEC_HASHES.txt` is 55 characters — 9 characters were dropped
   in transcription. The prereg file was never altered: its true
   SHA-256 is
   `58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b`,
   and the recorded token is exactly that string with a 9-char
   deletion (a copy-error signature). Child A computed the true
   hash before scoring, filed
   `specs/AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md` **before
   any scoring**, left `SPEC_HASHES.txt` unedited, and locked
   its evaluator on the true hash. The coordinator re-verified
   all five hashes from disk: the other four tokens are
   full-length and match. No construction, constant, split,
   metric, or gate was affected.
2. **A parallel evaluation outside this lane produced different
   numbers for the batter/pitcher families — reconcile before
   either set is relied on.** Child A received background
   completion messages for runs it did not execute: a batter run
   passing only Walks, and a pitcher run failing all four
   markets with B2 Outs CRPS 2.0267 vs this lane's 2.1705 — same
   fixture counts (38,511 / 3,382), different scores, the
   signature of a differently-constructed league baseline. This
   lane's B2 is the preregistered Phase 2 construction
   (expanding season-to-date, strictly prior dates; implementing
   lines quoted verbatim from the Phase 2 evaluator), and every
   headline number here was confirmed by a full deterministic
   re-run AND an independent recomputation from the raw cache.
   This lane did not spawn the other run and cannot certify its
   construction; if its league distribution was built
   full-season (in-sample), it would not be a valid PIT
   baseline. Flagged, not adjudicated.
3. **2026 league baselines are weaker than 2024–25.** On the 2026
   splits, B2 (expanding PIT league distribution) scores worse
   than it did in Phase 2's seasons (e.g., pitcher Outs CRPS
   2.1705 vs 2.0540 pooled 2024–25). The paired CIs below are
   the verdicts as preregistered; this context travels with the
   batter/pitcher B2 legs.

## Family 1 — MLB batter props

- **Preregistration:** `specs/PREREG_BATTER_PROPS.md`, SHA-256
  `58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b`
  (see flag 1); amendment: hash-record bookkeeping only.
- **Challenger (one paragraph):** B1 promoted to a full
  distribution plus the league shrinkage B1 lacked — for each
  fixture, the predictive PMF over the stat's counts is
  (empirical counts over the batter's UNCAPPED same-season prior
  games + 25 · the expanding league PMF) / (n + 25), one
  construction for all 13 stats; K = 25 predeclared, one shot.
- **Split discipline:** Phase 2 diagnosed on 2024–2025; test =
  **2026 regular season, SINGLE_SPLIT** (never scored or
  inspected by Phase 2). n = **38,511** fixtures (exclusions:
  NOT_A_STARTER 5,919; POOL_GAMES_LT_10 5,184; POOL_PA_LT_20
  10). Parity 28/28 vs production pools. Acquisition: 2,430/2,430
  boxscores, zero failures.
- **Verdicts (per stat; binary = Brier/log-loss gate, ladder =
  CRPS gate):** the challenger beats FROZEN and B1 on all 13
  stats with every CI entirely < 0; the B2 leg decides:
  - **ADOPT-CANDIDATE (10):** Hits (Brier 0.2367 vs FROZEN
    0.2441 / B1 0.2411 / B2 0.2377; Δ vs FROZEN −0.0074
    [−0.0083, −0.0065], vs B1 −0.0044 [−0.0055, −0.0033], vs B2
    −0.0010 [−0.0016, −0.0004]; log-loss legs pass likewise),
    Total Bases (the same event at the 0.5 line), Runs
    (Δ vs B2 −0.0009 [−0.0015, −0.0003]), Hits+Runs+RBIs
    (−0.0010 [−0.0015, −0.0005]), Singles (−0.0014
    [−0.0020, −0.0007]), Walks (−0.0045 [−0.0051, −0.0040]),
    Home Runs CRPS (−0.0010 [−0.0012, −0.0007]), Extra Base
    Hits CRPS (−0.0007 [−0.0012, −0.0003]), Batter Strikeouts
    CRPS (−0.0136 [−0.0147, −0.0126]), Runs+RBIs CRPS
    (−0.0014 [−0.0024, −0.0003]).
  - **KEEP FROZEN (3):** RBIs — beats FROZEN/B1, ties B2 on
    Brier (Δ −0.0004 [−0.0010, +0.0002]); Doubles —
    significantly **worse** than B2 (ΔBrier +0.0006
    [+0.0003, +0.0008]) despite beating FROZEN and B1; Triples
    — dead tie with B2 on CRPS (+0.0000 [−0.0000, +0.0001]).
  - Challenger and B2 had zero support misses on all 8 binary
    stats (FROZEN/B1 up to 158, on Doubles).
- **Recommendation:** ADOPT-CANDIDATE for the 10 stats above;
  KEEP FROZEN for RBIs, Doubles, Triples. Full numbers:
  `results/challenger_batter_props_results.json`.

## Family 2 — MLB pitcher undercard (Outs / Hits Allowed / Walks / Earned Runs)

- **Preregistration:** `specs/PREREG_PITCHER_UNDERCARD.md`,
  SHA-256
  `9628b9626ccd42ed04f836f32ed51aa62d0eeca6b72deac782e1ef8622c5a41c`
  (matches the locked record exactly; no amendment).
- **Challenger (one paragraph):** the pitcher's UNCAPPED raw
  trailing distribution (B1's pool) shrunk toward the league
  distribution — predictive PMF = (pool counts + 10 ·
  league PMF) / (n + 10), K = 10 starts-equivalent predeclared;
  the frozen arm is the production joint engine reconstructed by
  the Phase 2 CDF sweep (sweep sanity max deviation 5.6e-17).
- **Split discipline:** **2026 regular season, SINGLE_SPLIT**.
  n = **3,382** starts (only exclusion: POOL_STARTS_LT_5,
  1,462). Parity 25/25.
- **Verdicts (CRPS):**
  - Outs: FROZEN 2.1392 / CHALL 2.0512 / B1 2.1163 / B2
    2.1705; Δ vs FROZEN −0.0880 [−0.1078, −0.0682], vs B1
    −0.0651 [−0.0882, −0.0459], vs B2 −0.1193
    [−0.1350, −0.1035] → **ADOPT-CANDIDATE**.
  - Hits Allowed: 1.3080 / 1.2328 / 1.2926 / 1.2507; Δ
    −0.0753 / −0.0598 / −0.0180 [−0.0278, −0.0079] →
    **ADOPT-CANDIDATE**.
  - Walks: 0.7414 / 0.6900 / 0.7268 / 0.7003; Δ −0.0514 /
    −0.0369 / −0.0103 [−0.0163, −0.0042] →
    **ADOPT-CANDIDATE**.
  - Earned Runs: 1.1636 / 1.0976 / 1.1544 / 1.0951; beats
    FROZEN (−0.0660 [−0.0759, −0.0559]) and B1 (−0.0568) but
    ties B2 (+0.0024 [−0.0039, +0.0094]) → **KEEP FROZEN**.
- **Recommendation:** ADOPT-CANDIDATE for Outs, Hits Allowed,
  Walks; KEEP FROZEN for Earned Runs. Full numbers:
  `results/challenger_pitcher_undercard_results.json`.

## Family 3 — MLB first inning (YRFI/NRFI)

- **Preregistration:** `specs/PREREG_FIRST_INNING.md`, SHA-256
  `17b62221d554ca434fff1e62c458a570758d8b14c1c96bd0707d458706d3e3c9`
  (matches; no amendment).
- **Challenger (one paragraph):** the production binary
  construction (whose form Phase 2 confirmed; the Poisson sibling
  was not re-armed) with each component Jeffreys rate shrunk
  toward its expanding league rate, r′ = (x + 0.5 + 20 ·
  r_L) / (n + 1 + 20), A = 20 predeclared; the
  ½ team + ½ starter blend and the independence combination are
  production's, unchanged — "climatology with a shrunk tilt,"
  built literally.
- **Split discipline:** **2026 regular season, SINGLE_SPLIT**
  (Phase 2 diagnosed 2025 primary + 2024 secondary). n =
  **2,038** scored of 2,427 (exclusions:
  starter_history_insufficient 365, starter_unidentified 14,
  league-rate-undefined 10). Parity: pools 25/25, linescore
  spot integrity 10/10, A = 0 reduction-to-frozen 25/25.
- **Verdict:** arm Brier / log loss — FROZEN 0.24759 / 0.68829,
  CHALLENGER 0.24801 / 0.68915, B1 climatology 0.25039 /
  0.69392, B2 team-only 0.25503 / 0.70368. The challenger beats
  B1 (ΔBrier [−0.00368, −0.00096]) and B2 ([−0.00991,
  −0.00436]) but does **not** beat the frozen engine: ΔBrier vs
  FROZEN [−0.00092, +0.00174], ΔLogLoss [−0.00189, +0.00356] —
  both include 0, point estimate slightly worse. (Descriptive:
  the challenger is better calibrated — ECE 0.0026 vs frozen
  0.0212 — and worse scored; calibration alone was not the
  gate.) → **KEEP FROZEN.** The Phase 2 suspicion is now
  measured on untouched data: the unshrunk tilt is worth nothing
  the shrunk tilt can recover; on 2026 the family remains a
  climatology model with a decorative tilt, and its
  gated/research-only card posture stays correct.
- **Recommendation:** KEEP FROZEN. Full numbers:
  `results/challenger_first_inning_results.json`.

## Family 4 — MLB F5 score distributions

- **Preregistration:** `specs/PREREG_F5.md`, SHA-256
  `378a60071ba12895288bf419208855f3f319b3e397e0c48321257f81a824155c`
  (matches). **Amendment filed BEFORE scoring:**
  `specs/AMENDMENT_F5_STRENGTH_MECHANISM.md` — the prereg's §3
  premise was false at the frozen evaluand:
  `build_f5_distribution` rejects any strength outside {0, 30}
  and `_smoothed_pmf` reads the module-global
  `LEAGUE_PRIOR_STRENGTH`, not a parameter. The mathematical
  definition is unchanged (m90 smoothing of the same features,
  prior, and builder); the challenger was realized
  evaluator-side by temporarily rebinding that module global
  in-process — no repo edit — with the version-string caveat
  recorded in the results file. Scope guard held throughout:
  distributions only, readout never scored, `eligible=false`
  untouched.
- **Challenger (one paragraph):** the production F5 build with
  the league prior strengthened from 30 to 90 — the single
  lever Phase 2's evidence pointed at (m30 measurably beat the
  unsmoothed build; nothing else in the build separated from
  climatology).
- **Split discipline:** **TWO_SPLIT** — 2026 PRIMARY (Phase 2
  scored 2025 only), 2024 SECONDARY corroborating (sealed-window
  prior treatment exactly as Phase 2); splits never pooled.
  Parity 25/25 per split (features, PMF mass 1e-12, strength-30
  identity).
- **Verdict 2026 primary:** n = **2,401** (zero exclusions).
  Total-runs CRPS — FROZEN 1.8167 / CHALLENGER 1.8146 / B1
  1.8159 / B2 1.8313. Challenger ΔCRPS vs FROZEN
  [−0.00614, +0.00129] (tie), vs B1 [−0.00435, +0.00220] (tie),
  vs B2 [−0.03085, −0.00530] (beats). Joint log score: B1 best
  (4.1314 vs challenger 4.1429). → gate fails.
- **Verdict 2024 secondary:** n = **1,624**. CRPS — FROZEN
  1.7825 / CHALLENGER 1.7791 / B1 1.7785 / B2 1.7979;
  challenger Δ vs FROZEN [−0.00726, +0.00038] (tie), vs B1
  [−0.00336, +0.00435] (tie), vs B2 beats. Same shape — the
  secondary corroborates the primary; no contradiction to
  resolve.
- **Recommendation:** **KEEP FROZEN.** Tripling the prior moves
  the build in the measured direction and still never separates
  from m30 or from climatology on either untouched split; the
  F5 distribution is a league-distribution model with an
  unproven team tilt, exactly as Phase 2 described it. Full
  numbers: `results/challenger_f5_results.json`.

## Family 5 — CFB QB passing yards

- **Preregistration:** `specs/PREREG_CFB_QB.md`, SHA-256
  `319629eee535bba913953c9178c6f4216476c453ff2231627647ae2fde85ca25`
  (matches; no amendment). Governance scope held: CFB Attempt 1
  unspent and untouched; the family stays UNREGISTERED and
  UNVALIDATED regardless of outcome.
- **Challenger (one paragraph):** the B2 team-attempt chain
  carrying the production builder as a shrunk adjustment — a
  mixture distribution, F_chal = 0.25 · F_builder + 0.75 ·
  F_team-chain (the exact CDF-level mixture of the preregistered
  per-path γ = 0.25 draw; γ the only value scored, no sweep).
  The identity rule (plurality over all prior games) is
  production's, deliberately unchanged.
- **Split discipline:** **2024 season, SINGLE_SPLIT** (Phase 2
  diagnosed 2025 + 2026-partial; 2024 games served only as prior
  history). Assembly: ESPN game summaries (the Phase 2
  implementation's actual source, mirrored); 1,939 runway events
  (2022–2023) acquired before scoring, 0 failures; 2024 FBS set
  derived fresh = 134 schools, 134/134 matched. Verification:
  Collins reproduction PASS (mean 174.43 vs 174.4 ± 1.5; shares
  within ±0.01); assembly audit 9/10 exact (the miss was a
  gamelog-coverage gap, not a value disagreement); leakage
  tripwire 10/10 both halves.
- **Population:** n = **417** scored of 1,695 candidate
  team-games. Exclusions: ROLE_NOT_MATERIALIZED 1,191 (**70.3%**
  — higher than 2025's 59%; the scored population is QB-stable
  teams, as preregistered), ILLINOIS_EXCLUDED 74,
  BUILDER_REFUSAL 13, INSUFFICIENT_PIT_HISTORY 0,
  IDENTITY_NOT_ESTABLISHED 0.
- **Verdict (CRPS; 20,000 paths):** FROZEN 47.821 / CHALLENGER
  **44.343** / B1 47.777 / B2 44.916. Paired ΔCRPS — vs FROZEN
  [−4.862, −2.142], vs B1 [−4.779, −2.056], vs B2
  [−0.967, −0.172]: all three entirely < 0, including the pure
  team chain — the QB links carry real signal once shrunk to a
  25% adjustment. Calibration improved (p5–p95 coverage 0.935
  vs frozen 0.947; nominal 0.90). → **ADOPT-CANDIDATE.**
- **Recommendation:** ADOPT-CANDIDATE for Isaac. The challenger
  fixes the distribution, not the family's coverage problem —
  the 70.3% role exclusion is the identity rule's measured
  shadow and remains the CFB lane's window decision. Full
  numbers: `results/challenger_cfb_qb_results.json`.

## Lane A (MLB game model) — record only, per instructions

No new challenger was started in this lane. On the record:
Lane A itself is DOES_NOT_BEAT_MARKET (n = 10,237; Brier
0.247856 vs market 0.236332); the precedent-Elo challenger
exists and is BEATS_LANE_A_ONLY (Brier 0.242667 — beats Lane A,
does not beat the market); the Elo→Poisson challenger failed.
Lane A's state is unchanged by this lane: challenger exists,
market leg still failing, production frozen.

## Summary of recommendations

| Family | Split(s) | n | Verdict |
|---|---|---|---|
| Batter props | 2026 | 38,511 | **ADOPT-CANDIDATE ×10 stats; KEEP FROZEN ×3** (RBIs, Doubles, Triples) |
| Pitcher undercard | 2026 | 3,382 | **ADOPT-CANDIDATE ×3 markets** (Outs, Hits Allowed, Walks); **KEEP FROZEN** Earned Runs |
| First inning | 2026 | 2,038 | **KEEP FROZEN** (beats both baselines, not the frozen engine) |
| F5 distributions | 2026 + 2024 | 2,401 + 1,624 | **KEEP FROZEN** (ties frozen m30 and climatology on both splits) |
| CFB QB passing | 2024 | 417 | **ADOPT-CANDIDATE** (beats frozen, B1, and B2) |
| Lane A | — | — | Record only: challenger exists, BEATS_LANE_A_ONLY, market leg still failing |

Every ADOPT-CANDIDATE is a recommendation to Isaac and nothing
more: adoption is an owner act, sequenced after the M2/M4 market
verdicts publish, and would ship as new production code under
its own review. Every KEEP FROZEN closes its challenger — no
constant (K = 25, K = 10, A = 20, strength 90, γ = 0.25) may be
re-tuned on the split that just judged it; a second challenger
for any family requires a new preregistration and a new
untouched split. Negative verdicts are reported in full by
design: three of the five failed constructions are now measured
to fail in both directions (their frozen forms AND their
shrunk challengers), which is itself the refine/recalibrate
evidence — for first inning and F5, the league distribution is
not a baseline the current constructions beat in any tested
form.

**Files:** `specs/` (5 preregistrations + SPEC_HASHES.txt + 2
amendments) · `scripts/` (5 evaluators + acquisition + FBS 2024
derivation) · `results/` (5 results JSONs + parity/verification
artifacts) · this report.
