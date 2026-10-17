# Shrinkage Challenger Adoption — Records Package

**Assembled:** Oct 15, 2026, at Isaac's request (the 14 claimed
shrinkage ADOPT-CANDIDATEs "still need identifiable source and
evaluation records" before an adoption ruling).
**Source lane:** Model Fix Lane, Oct 14 2026 —
`~/workspace/sportsedge/model_fix_20261014/` (`REPORT.md`,
`specs/`, `scripts/`, `results/`).
**Verification method:** every number below was read from the
on-disk results JSONs, not copied from the lane report; every
preregistration hash was recomputed with `sha256sum` from the
files on disk and compared against `specs/SPEC_HASHES.txt` and
the hashes recorded inside the results JSONs. Discrepancies are
listed in §5 — including the ones the lane flagged itself.
**Frozen evaluand (all families):** origin/main `2a713380c`;
nine evaluand files verified byte-identical to the Phase 2
evaluand at `12999fc22` (recorded in the results JSONs).
**Label of all evidence:** RESEARCH_EVIDENCE — retrospective
calibration evidence on declared untouched splits. Production
was never edited by the lane.
**Repository publication:** Oct 15, 2026 — this package is
published in the SportsEdge repository at
`research/shrinkage_adoption_records/` (branch
`research/shrinkage-adoption-records-20261015`) so the
challengers can be certified from identifiable records rather
than from a lane workspace alone. `specs/`, `results/`, and
`scripts/` are byte-identical copies of the lane files named
above; `REPORT.md` is the lane's own report.
`SPEC_HASHES.txt` ships byte-as-is; its batter token defect
(D1) is governed by `AMENDMENT_BATTER_HASH.md` in this
package, not by editing the locked record. Post-assembly
update: discrepancy **D2 is RESOLVED** (see §5) on the
evidence in `D2_RECONCILIATION.md`, included in this package.

## The distinction Isaac asked about — stated plainly

**None of the 14 evaluations was ever scored against market
prices.** Every preregistration and every results JSON carries
the label verbatim: *"NOT a market verdict, NOT validation, NOT
a promotion input."* The arms in every evaluation are exactly
four: FROZEN (the production engine), CHALLENGER, B1 and B2
(simple statistical baselines defined below). No sportsbook
price, no-vig line, or closing line appears anywhere as a scored
arm. What these records establish is **improvement over the
frozen model and over simple baselines on out-of-sample
outcomes** — nothing about beating market prices. (The lane's
own sequencing note says adoption candidacy was to be
considered only after the separate M2/M4 market-leg verdicts
publish; those market legs are a different record set, in the
backtest program lane.)

## Adoption gate (preregistered, identical shape in all three preregs)

ADOPT-CANDIDATE iff the challenger's paired Δ CIs are
**entirely < 0 against FROZEN AND B1 AND B2** — batter family:
on both ΔBrier and ΔLogLoss for binary stats, on ΔCRPS for
ladder stats; pitcher and CFB families: on ΔCRPS. CIs are
paired, ISO-week block bootstrap, 2,000 resamples, seed
20261015. Any other outcome = KEEP FROZEN.

## Summary table — the 14 ADOPT-CANDIDATEs

| # | Challenger | Form | Split / n | Gate-metric Δ vs B2 (binding leg) | Gate |
|---|---|---|---|---|---|
| 1 | Batter Hits | (counts + 25·league)/(n+25) | 2026, n=38,511 | ΔBrier −0.0010 [−0.0016, −0.0004] | PASS |
| 2 | Batter Total Bases | same construction | 2026, n=38,511 | ΔBrier −0.0010 [−0.0016, −0.0004] | PASS (see D3) |
| 3 | Batter Runs | same | 2026, n=38,511 | ΔBrier −0.0009 [−0.0015, −0.0003] | PASS |
| 4 | Batter Hits+Runs+RBIs | same | 2026, n=38,511 | ΔBrier −0.0010 [−0.0015, −0.0005] | PASS |
| 5 | Batter Singles | same | 2026, n=38,511 | ΔBrier −0.0014 [−0.0020, −0.0007] | PASS |
| 6 | Batter Walks | same | 2026, n=38,511 | ΔBrier −0.0045 [−0.0051, −0.0040] | PASS |
| 7 | Batter Home Runs | same | 2026, n=38,511 | ΔCRPS −0.0010 [−0.0012, −0.0007] | PASS |
| 8 | Batter Extra-Base Hits | same | 2026, n=38,511 | ΔCRPS −0.0007 [−0.0012, −0.0003] | PASS |
| 9 | Batter Strikeouts | same | 2026, n=38,511 | ΔCRPS −0.0136 [−0.0147, −0.0126] | PASS |
| 10 | Batter Runs+RBIs | same | 2026, n=38,511 | ΔCRPS −0.0014 [−0.0024, −0.0003] | PASS |
| 11 | Pitcher Outs | (counts + 10·league)/(n+10) | 2026, n=3,382 | ΔCRPS −0.1193 [−0.1350, −0.1035] | PASS |
| 12 | Pitcher Hits Allowed | same | 2026, n=3,382 | ΔCRPS −0.0180 [−0.0278, −0.0079] | PASS |
| 13 | Pitcher Walks (BB) | same | 2026, n=3,382 | ΔCRPS −0.0103 [−0.0163, −0.0042] | PASS |
| 14 | CFB QB passing yards | 0.25·builder + 0.75·team-chain mixture | 2024, n=417 | ΔCRPS CI [−0.967, −0.172] | PASS |

Evaluated in the same runs and **not** candidates (KEEP FROZEN,
for the completeness of the count): Batter RBIs (ties B2),
Batter Doubles (significantly worse than B2), Batter Triples
(dead tie with B2), Pitcher Earned Runs (ties B2). First-inning
and F5 challengers also failed their gates and are not
shrinkage-adoption items.

---

## 1–10. Batter props challengers

**Shared construction (one challenger for all 13 stats):**
predictive PMF over the stat's counts =
(empirical counts over the batter's UNCAPPED same-season prior
games + 25 · the expanding league PMF) / (n + 25); K = 25
predeclared, one shot. (Per-stat entries below therefore share
the form; the scored PMF is per stat.)
**Preregistration:** `model_fix_20261014/specs/PREREG_BATTER_PROPS.md`
— SHA-256 recomputed from disk:
`58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b`.
⚠️ The token recorded for this file in `specs/SPEC_HASHES.txt`
is a defective 55-character string (9 chars deleted at offset
49) — see discrepancy **D1**. The results JSON records both the
true hash and the defective token; the evaluator locked on the
true hash under a pre-scoring amendment
(`specs/AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md`).
**Evaluation design:** design/diagnosis on 2024–2025 (Phase 2);
test = 2026 regular season, SINGLE_SPLIT, never scored or
inspected by Phase 2. n = 38,511 fixtures for every stat
(exclusions: NOT_A_STARTER 5,919; POOL_GAMES_LT_10 5,184;
POOL_PA_LT_20 10; acquisition 2,430/2,430 boxscores, zero
failures). Parity 28/28 vs production pools (verification JSON
on disk). Arms: FROZEN = production `price_batter_market`;
B1 = batter's own raw trailing empirical distribution;
B2 = expanding season-to-date league distribution (Phase 2
constructions, implementing lines quoted verbatim in the
results JSON).
**Results file:** `results/challenger_batter_props_results.json`
(+ `challenger_batter_props_parity.json`,
`challenger_batter_props_verification.json`).
**Market scoring:** NONE — outcomes only (see header).

Binary stats (gate = ΔBrier AND ΔLogLoss, all three legs
entirely < 0; scores are Brier for FROZEN / CHALL / B1 / B2):

### 1. Hits (O/U 0.5 form)
Scores 0.2441 / 0.2367 / 0.2411 / 0.2377. ΔBrier vs FROZEN
−0.0074 [−0.0083, −0.0065]; vs B1 −0.0044 [−0.0055, −0.0033];
vs B2 −0.0010 [−0.0016, −0.0004]. ΔLogLoss vs FROZEN −0.0172
[−0.0193, −0.0153]; vs B1 −0.0102 [−0.0131, −0.0077]; vs B2
−0.0021 [−0.0032, −0.0009]. **Gate: PASS** (JSON verdict
ADOPT-CANDIDATE).

### 2. Total Bases (O/U 0.5 form)
Metrics byte-identical to Hits — at the 0.5 line the two events
are the same event (a total base is recorded only via a hit).
Same scores, same deltas, same CIs. **Gate: PASS** (JSON
verdict ADOPT-CANDIDATE). See **D3**: this is one evaluation
wearing two market names, not two independent results.

### 3. Runs (O/U 0.5 form)
Scores 0.2423 / 0.2353 / 0.2393 / 0.2362. ΔBrier vs FROZEN
−0.0070 [−0.0082, −0.0060]; vs B1 −0.0040 [−0.0055, −0.0028];
vs B2 −0.0009 [−0.0015, −0.0003]. ΔLogLoss vs FROZEN −0.0230
[−0.0298, −0.0179]; vs B1 −0.0155 [−0.0232, −0.0098]; vs B2
−0.0019 [−0.0032, −0.0005]. **Gate: PASS.**

### 4. Hits+Runs+RBIs (O/U 0.5 form)
Scores 0.2237 / 0.2166 / 0.2206 / 0.2177. ΔBrier vs FROZEN
−0.0070 [−0.0079, −0.0063]; vs B1 −0.0040 [−0.0051, −0.0030];
vs B2 −0.0010 [−0.0015, −0.0005]. ΔLogLoss vs FROZEN −0.0178
[−0.0202, −0.0160]; vs B1 −0.0102 [−0.0135, −0.0076]; vs B2
−0.0024 [−0.0035, −0.0013]. **Gate: PASS.**

### 5. Singles (O/U 0.5 form)
Scores 0.2536 / 0.2464 / 0.2505 / 0.2477. ΔBrier vs FROZEN
−0.0073 [−0.0084, −0.0063]; vs B1 −0.0041 [−0.0055, −0.0030];
vs B2 −0.0014 [−0.0020, −0.0007]. ΔLogLoss vs FROZEN −0.0186
[−0.0214, −0.0161]; vs B1 −0.0112 [−0.0147, −0.0083]; vs B2
−0.0027 [−0.0039, −0.0014]. **Gate: PASS.**

### 6. Walks (O/U 0.5 form)
Scores 0.2109 / 0.2054 / 0.2081 / 0.2099. ΔBrier vs FROZEN
−0.0056 [−0.0064, −0.0048]; vs B1 −0.0027 [−0.0037, −0.0019];
vs B2 −0.0045 [−0.0051, −0.0040]. ΔLogLoss vs FROZEN −0.0263
[−0.0326, −0.0209]; vs B1 −0.0170 [−0.0236, −0.0116]; vs B2
−0.0109 [−0.0123, −0.0095]. **Gate: PASS.**

Ladder stats (gate = ΔCRPS, all three legs entirely < 0;
scores are CRPS for FROZEN / CHALL / B1 / B2):

### 7. Home Runs (ladder CRPS)
Scores 0.1141 / 0.1113 / 0.1128 / 0.1123. ΔCRPS vs FROZEN
−0.0028 [−0.0032, −0.0025]; vs B1 −0.0014 [−0.0020, −0.0010];
vs B2 −0.0010 [−0.0012, −0.0007]. **Gate: PASS.**

### 8. Extra-Base Hits (ladder CRPS)
Scores 0.2395 / 0.2333 / 0.2366 / 0.2341. ΔCRPS vs FROZEN
−0.0061 [−0.0070, −0.0053]; vs B1 −0.0033 [−0.0045, −0.0023];
vs B2 −0.0007 [−0.0012, −0.0003]. **Gate: PASS.**

### 9. Batter Strikeouts (ladder CRPS)
Scores 0.4537 / 0.4433 / 0.4490 / 0.4569. ΔCRPS vs FROZEN
−0.0104 [−0.0121, −0.0090]; vs B1 −0.0057 [−0.0077, −0.0041];
vs B2 −0.0136 [−0.0147, −0.0126]. **Gate: PASS.** (Note: B2
is the worst arm on this stat — the league distribution is a
weak baseline here; the binding constraint was B1.)

### 10. Runs+RBIs (ladder CRPS)
Scores 0.6393 / 0.6215 / 0.6310 / 0.6229. ΔCRPS vs FROZEN
−0.0178 [−0.0201, −0.0159]; vs B1 −0.0096 [−0.0129, −0.0069];
vs B2 −0.0014 [−0.0024, −0.0003]. **Gate: PASS.**

---

## 11–13. Pitcher undercard challengers

**Shared construction:** predictive PMF = (pool counts + 10 ·
league PMF) / (n + 10), where the pool is the pitcher's
UNCAPPED raw trailing same-season starts distribution and the
league PMF is the expanding season-to-date pooled distribution
over all starters' prior starts; K = 10 predeclared. The frozen
arm is the production joint engine reconstructed by the Phase 2
CDF sweep (sweep sanity max deviation 5.6e-17, recorded in the
results JSON).
**Preregistration:**
`model_fix_20261014/specs/PREREG_PITCHER_UNDERCARD.md` —
SHA-256 recomputed from disk:
`9628b9626ccd42ed04f836f32ed51aa62d0eeca6b72deac782e1ef8622c5a41c`,
matching `SPEC_HASHES.txt` exactly; no amendment.
**Evaluation design:** design on 2024–2025 (Phase 2); test =
2026 regular season, SINGLE_SPLIT. n = 3,382 starts for every
market (only exclusion: POOL_STARTS_LT_5, 1,462 of 4,844
candidate starts). Parity 25/25 (verification JSON on disk,
`challenger_pitcher_undercard_verification.json`, parity
PASSED 25/25). Arms: FROZEN = production `price_pitcher_market`;
B1 = pitcher's own raw trailing distribution; B2 = league
distribution.
**Results file:** `results/challenger_pitcher_undercard_results.json`.
**Market scoring:** NONE — outcomes only (see header).
Scores below are CRPS for FROZEN / CHALL / B1 / B2; gate =
ΔCRPS all three legs entirely < 0.

### 11. Outs
Scores 2.1392 / 2.0512 / 2.1163 / 2.1705. Δ vs FROZEN −0.0880
[−0.1078, −0.0682]; vs B1 −0.0651 [−0.0882, −0.0459]; vs B2
−0.1193 [−0.1350, −0.1035]. **Gate: PASS** (JSON verdict
ADOPT-CANDIDATE).

### 12. Hits Allowed
Scores 1.3080 / 1.2328 / 1.2926 / 1.2507. Δ vs FROZEN −0.0753
[−0.0917, −0.0604]; vs B1 −0.0598 [−0.0785, −0.0444]; vs B2
−0.0180 [−0.0278, −0.0079]. **Gate: PASS** (JSON verdict
ADOPT-CANDIDATE).

### 13. Walks (engine market PITCHER_BB)
Scores 0.7414 / 0.6900 / 0.7268 / 0.7003. Δ vs FROZEN −0.0514
[−0.0619, −0.0423]; vs B1 −0.0369 [−0.0482, −0.0274]; vs B2
−0.0103 [−0.0163, −0.0042]. **Gate: PASS** (JSON verdict
ADOPT-CANDIDATE).

(Not a candidate: Earned Runs — scores 1.1636 / 1.0976 /
1.1544 / 1.0951; beats FROZEN and B1 but ties B2, Δ +0.0024
[−0.0039, +0.0094] → KEEP FROZEN, correctly excluded from the
14.)

---

## 14. CFB QB passing yards challenger

**Construction:** CDF-level mixture F_chal = 0.25 · F_builder
+ 0.75 · F_team-chain — the exact pooled-mixture distribution
of the preregistered per-path draw (each simulated path drawn
from the production builder's distribution with probability
γ = 0.25, from the B2 team-attempt chain with probability
0.75). γ = 0.25 is the only value scored; no sweep. 20,000
paths per fixture. The QB identity rule (plurality over all
prior games) is production's, unchanged.
**Preregistration:** `model_fix_20261014/specs/PREREG_CFB_QB.md`
— SHA-256 recomputed from disk:
`319629eee535bba913953c9178c6f4216476c453ff2231627647ae2fde85ca25`,
matching `SPEC_HASHES.txt` exactly (the results JSON also
records `locked_sha256_in_SPEC_HASHES` = same value); no
amendment.
**Evaluation design:** design/diagnosis on 2025 +
2026-partial (Phase 2); test = 2024 season, SINGLE_SPLIT (2024
games served only as prior history for later predictions;
priors reach into 2022–2023 via ESPN summary assembly; 1,939
runway events acquired, 0 failures; 2024 FBS set derived fresh,
134/134 schools matched). n = **417 scored of 1,695 candidate
team-games** — exclusions: ROLE_NOT_MATERIALIZED 1,191 (70.3%),
ILLINOIS_EXCLUDED 74, BUILDER_REFUSAL 13 (see **D4**).
Verification on disk in the results JSON: Collins reproduction
PASS (mean 174.43 vs 174.4 ± 1.5); leakage tripwire 10/10 both
halves. Arms: FROZEN = production builder; B1 = QB trailing
empirical distribution; B2 = team-attempt chain.
**Results file:** `results/challenger_cfb_qb_results.json`.
**Market scoring:** NONE — outcomes only (see header).
**Headline result (CRPS):** FROZEN 47.821 / CHALLENGER 44.343
/ B1 47.777 / B2 44.916. Paired ΔCRPS CIs (point deltas
computed from the recorded arm means): vs FROZEN −3.478,
CI [−4.862, −2.142]; vs B1 −3.434, CI [−4.779, −2.056];
vs B2 −0.573, CI [−0.967, −0.172]. All three entirely < 0.
Calibration: p5–p95 coverage 0.935 (challenger) vs 0.947
(frozen), nominal 0.90.
**Gate: PASS** (JSON `gate_verdict` = ADOPT-CANDIDATE).
**Governance caveat (part of the record):** the family stays
UNREGISTERED and UNVALIDATED regardless of this outcome; CFB
Attempt 1 is unspent and untouched by this evaluation.
Adoption here would be adoption of a research distribution,
not a validation.

---

## 5. Discrepancies and flags found during verification

**No numeric discrepancies were found between the lane
REPORT.md and its own results JSONs.** Every score, delta, and
CI quoted in the report for all 14 challengers (and for the
five KEEP FROZEN outcomes) was checked against the on-disk
JSONs and matches at the reported precision. The flags below
are record-integrity and interpretation items, not arithmetic
errors.

- **D1 — Batter-props spec-hash record defect (lane-flagged;
  verified on disk).** The `PREREG_BATTER_PROPS.md` line in
  `specs/SPEC_HASHES.txt` carries a 55-character token
  (`58a7977c…a3b6d1a65e3b` with 9 characters deleted at offset
  49), not the file's true 64-character SHA-256
  (`58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b`,
  recomputed in this audit — the preregistration file itself
  is intact and hashes correctly). The lane caught this before
  scoring, filed `AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md`,
  left `SPEC_HASHES.txt` unedited, and locked the evaluator on
  the true hash; the results JSON records both tokens and the
  mismatch explicitly. The audit chain is fully reconstructible,
  but the lock file as it stands does **not** verify for the
  batter family — one link in the chain is an amendment, not
  the original record. The other four preregistrations'
  tokens in `SPEC_HASHES.txt` are full-length and match their
  files exactly (recomputed in this audit). For the published
  repository record, the formal amendment is
  `AMENDMENT_BATTER_HASH.md` in this package; it supersedes
  the defective token for verification purposes going
  forward, and `SPEC_HASHES.txt` itself ships unedited.
- **D2 — Contested parallel numbers (lane-flagged;
  RESOLVED Oct 15–16, 2026).** A parallel evaluation outside
  this lane (owner-lane draft PRs #2311/#2312/#2314) produced
  different batter/pitcher figures on the same fixture counts
  (38,511 / 3,382) — e.g., pitcher B2 Outs CRPS 2.0267 there
  vs 2.1705 here. This lane's 2.1705 is the value in the
  on-disk results JSON, and the lane states its numbers were
  confirmed by a full deterministic re-run and an independent
  recomputation from the raw cache; its B2 is the
  preregistered Phase 2 construction (expanding,
  strictly-prior). The parallel construction could not be
  certified from this lane's files.
  **Resolution (post-assembly reconciliation — full record in
  `D2_RECONCILIATION.md`, included in this package):** under
  the preregistered B2 definition (league distribution =
  pooled empirical distribution over all starters' prior
  starts in the season to date, identical construction to
  Phase 2's B2; step-sum CRPS over outs 0–27), the correct
  value is **2.1705**, reproduced three independent ways: the
  recorded results JSON; a full re-run of the lane's evaluator
  against its frozen StatsAPI cache, byte-for-value identical
  on the headline line; and an independent recomputation from
  the raw cache (step-sum and identity CRPS forms agree).
  The parallel figure **2.0267 is unattributable to any
  persisted computation**: no code and no results file
  containing it exists in the workspace or in any git ref —
  the three owner-lane draft branches contain no pitcher-CRPS
  code at all — and no single-ingredient deviation from the
  preregistered construction (pool window, pool membership,
  PIT cutoff, CRPS form, index convention, outcome
  conversion, summary statistic, or scoring subset)
  transforms 2.1705 into 2.0267 on the same fixtures (the
  closest toggle is still 0.127 away, and every PIT-leakage
  toggle moves the value the wrong way). Rely on 2.1705 and
  the pitcher gate verdicts that stand on it; treat 2.0267 as
  withdrawn-by-unverifiability. If the parallel figure is to
  be reconsidered, the burden is a persisted evaluator +
  results file — the standard this package meets.
- **D3 — Total Bases ≡ Hits at the 0.5 line.** Challengers #1
  and #2 have byte-identical metrics in the results JSON
  because, scored as O/U 0.5 binaries, they are the same event.
  The lane report discloses this ("the same event at the 0.5
  line"). Counted honestly: the batter family contributes 9
  distinct evaluated stats + 1 duplicate-form stat to the 10
  batter candidates.
- **D4 — CFB scored-population caveat.** The CFB verdict rests
  on 417 of 1,695 candidate team-games; 70.3% were excluded as
  ROLE_NOT_MATERIALIZED, so the scored population is QB-stable
  teams only — as preregistered, but the record should not be
  read as covering the family's full population. The
  challenger fixes the distribution on that subpopulation, not
  the coverage problem.
- **D5 — 2026 B2 baselines are weaker than their 2024–25
  selves (lane-flagged context).** On the 2026 splits, B2 (the
  expanding league distribution) scores worse than it did in
  Phase 2's seasons (e.g., pitcher Outs B2 CRPS 2.1705 in 2026
  vs 2.0540 pooled 2024–25). The B2 legs of the 2026 gates were
  therefore run against a weaker-than-historical league
  baseline. The paired CIs stand as preregistered; the context
  travels with them.

## 6. Record-completeness verdicts

| Challenger | Verdict | Basis |
|---|---|---|
| Batter Hits | RECORD_PARTIAL | Complete prereg + results + parity/verification on disk; lock-file token defective (D1, documented + remediated by pre-scoring amendment) |
| Batter Total Bases | RECORD_PARTIAL | Same as Hits; also duplicate-form evaluation (D3) |
| Batter Runs | RECORD_PARTIAL | Same family record (D1) |
| Batter Hits+Runs+RBIs | RECORD_PARTIAL | Same family record (D1) |
| Batter Singles | RECORD_PARTIAL | Same family record (D1) |
| Batter Walks | RECORD_PARTIAL | Same family record (D1) |
| Batter Home Runs | RECORD_PARTIAL | Same family record (D1) |
| Batter Extra-Base Hits | RECORD_PARTIAL | Same family record (D1) |
| Batter Strikeouts | RECORD_PARTIAL | Same family record (D1) |
| Batter Runs+RBIs | RECORD_PARTIAL | Same family record (D1) |
| Pitcher Outs | RECORD_COMPLETE | Prereg hash verifies end-to-end; results + parity/verification on disk; all figures cross-checked (D2 resolved in favor of this lane's values — see §5 and `D2_RECONCILIATION.md`) |
| Pitcher Hits Allowed | RECORD_COMPLETE | Same |
| Pitcher Walks | RECORD_COMPLETE | Same |
| CFB QB passing (mixture) | RECORD_COMPLETE | Prereg hash verifies end-to-end; results on disk incl. assembly, identity, and tripwire records; population caveat D4 is part of the record |

Nothing among the 14 is RECORD_MISSING: every challenger has
an identifiable preregistration file, an identifiable evaluator
(`scripts/eval_challenger_*.py`), and an identifiable results
JSON on disk. The single record defect is D1 (shipped as-is
and governed by amendment, not edited). The external conflict
D2 was resolved after assembly, in favor of this lane's set —
see §5 D2 and `D2_RECONCILIATION.md`.
