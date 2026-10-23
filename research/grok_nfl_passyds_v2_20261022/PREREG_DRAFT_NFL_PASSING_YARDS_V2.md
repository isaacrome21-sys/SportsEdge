# DRAFT preregistration: NFL passing-yards construction v2 (NOT FROZEN)

Status: DRAFT, written Thu 2026-10-22 (CT) by Grok (verification lane). It has no force until the owner freezes it.
Label: RESEARCH_ONLY / NOT_VALIDATED. Nothing here is a PLAY. v1 (Part 2 / 2B) is untouched and keeps its frozen clock.

## 1. The defect, measured (repo data, pinned hashes)
Data: the nflverse weekly snapshot pinned in `research/nfl_props_part2_20261018/SPEC_HASHES.txt`. All 8 sha256 values were re-verified on Oct 22.
Estimator: the frozen v1 `mu_for` (K = 3 shrinkage toward the league pool), PASS_YDS gate, 2020–2025, weeks 4+, n = 2,360. That is the frozen population.
The CIs come from a 2,000-resample bootstrap clustered by season-week.

- v1 bias (mu − y): **+7.19 yd [3.57, 10.81]**. The handoff's "~10 yd" overstates it.
- The bias is not steady:
  - **By season:** 2020 +4.4, 2021 +18.0, 2022 +11.1, 2023 +6.6, 2024 −2.4, 2025 +5.8.
  - **By week phase:** weeks 4–6 −0.9, 7–11 +6.8, 12–18 +10.6.
  - **By prior-mean tercile:** low +4.6, mid +4.6, high +11.2.

## 2. Historical screen of candidate corrections (already run, so it is disclosed, not blind)
Every correction is point-in-time and uses only strictly earlier data. CRPS uses the frozen v1 gamma shape (cv = 0.3496). ΔCRPS is v2 − v1, and lower is better. v1 CRPS is 45.633.

| Candidate | Bias | ΔCRPS [95% CI] |
|---|---|---|
| C: × Σy/Σmu over prior seasons | −3.44 | +0.254 [−0.020, +0.527] |
| D: + mean(y − mu) over prior seasons | −4.11 | +0.358 [+0.061, +0.663] (worse) |
| E: × ratio by week phase × prior-mean tercile, prior seasons | −2.53 | +0.191 [−0.101, +0.494] |
| **F: × in-season ratio, current season's earlier weeks, shrunk to 1 with K = 200 rows** | +5.71 | **−0.066 [−0.150, +0.016]** |
| F with K = 50 | +5.03 | −0.031 [−0.163, +0.101] |

What the screen shows:
- Every correction learned from prior seasons overcorrects and makes CRPS worse. The bias changes from season to season, so a level carried over from earlier seasons doesn't transfer.
- Only the in-season correction F improves on v1, and only in the point estimate. Its CI includes 0, so it is **not** a demonstrated improvement.
- Six candidates were tried on the same data. F's lead is partly a selection effect.

## 3. Proposed v2 construction (F, constants fixed now)
- mu_v2 = mu_v1 × r.
- r = (Σy + K·m̄) / (Σmu_v1 + K·m̄).
  - The sums run over all PASS_YDS-qualified rows in weeks 4+ of the current season, in weeks strictly before the game.
  - m̄ is the mean mu_v1 of those rows, and K = 200.
  - With no rows yet, r = 1.
- Everything else is v1 exactly: the gate, the K = 3 shrinkage, the pool, the gamma cv, and the line-proxy diagnostics.

## 4. Freeze gate: the screen must show lower CRPS before any freeze
The historical screen has already been seen, so it can't serve as the gate. The gate is a forward screen instead:
- **Population:** 2026 regular season, weeks 8 and later, on nflverse data published after this draft's commit. Scoring stops after 4 full weeks.
- **Pass condition:** mean ΔCRPS (v2 − v1) < 0, AND the 95% season-week-clustered CI upper bound < 0, AND |bias_v2| < |bias_v1|.
- **If the screen fails,** v2 is not frozen, and the attempt is recorded as FAILED_SCREEN.
- **Freeze:** only after the screen passes and the owner rules. v2's forward market clock (the Part 2 CLV rules, including the ruling #1 v1.1 moved-line bucket and the ruling #2 single-review memo) starts at the freeze. It is scored alongside v1, and neither verdict affects the other.

## 5. Honest expectation
The historical evidence says the improvement, if real, is small: about 0.07 CRPS out of 45.6. The owner may prefer to leave v1 running unchanged and treat the bias as a disclosed annotation, the way 2B handles its busiest-QB warning.
