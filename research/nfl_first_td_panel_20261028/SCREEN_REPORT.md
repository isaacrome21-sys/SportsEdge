# NFL FIRST TD — design-screen report (NFL_FIRST_TD_V1)

Screen specified by `PREREG_NFL_FIRST_TD_FORWARD_V1_DRAFT.md`
section 1, run 2026-10-28 on the admitted first-scoring
attribution panel (`ADMISSION_AND_BUILD_RECORD.md` in this
directory; panel sha256
11867ac3be6ee75c086e6069e2c914fd13aa01da529d1359b638874efdc24cd4).
Runner: `screen_nfl_first_td_v1.py`; machine results:
`screen_results.json` (deterministic; seed 20261028, 10,000
game-cluster bootstrap resamples).

## Verdict: FAILED_SCREEN

Per the prereg draft section 1, the construction does not
advance. It may return only as a new version.

## Criteria, verbatim from the prereg draft

1. Beat baseline B1 (anytime-share-only: stage 2 collapsed to the
   shrunk anytime shares, stage 1 unchanged) on mean log loss over
   all games in the panel, game-clustered 95% CI for the
   difference entirely below 0.
2. Beat baseline B2 (league positional pool only) the same way.
3. Top-decile stated probabilities must not overstate realized
   frequency by more than 10 points.

## Results

Panel games 2020–2025: 1,693. Games in the paired means: 1,682
(11 games left the paired means because at least one arm assigned
exactly zero to the realized outcome — tallied below, never
floored; 0 games were out-of-space: every realized scorer was in
the candidate space).

Mean log loss: **V1 3.3666 · B1 3.1992 · B2 3.3825**.

| Criterion | Difference (V1 − baseline) | 95% CI | Verdict |
| --- | --- | --- | --- |
| 1 vs B1 | **+0.1674** | [+0.1397, +0.1952] | FAIL — CI entirely ABOVE 0 |
| 2 vs B2 | −0.0158 | [−0.0680, +0.0377] | FAIL — CI spans 0 |
| 3 top decile | stated 7.82% vs realized 5.98% (overstatement 1.8 pts, n = 16,766) | — | PASS |

Per-season Δ vs B1 is positive (V1 worse) in **all six seasons**
(2020 +0.118, 2021 +0.189, 2022 +0.245, 2023 +0.134, 2024 +0.156,
2025 +0.160). Per-season Δ vs B2 is mixed (−0.120 to +0.178). The
failure is uniform, not one bad season.

Zero-probability realized outcomes (log loss +inf, reported per
arm): V1 5, B1 5 — the identical five games, each its season's
first no-touchdown game (2021_09_BUF_JAX, 2022_05_IND_DEN,
2023_13_LAC_NE, 2024_15_LA_SF, 2025_18_KC_LV): before a season's
first no-TD game, the point-in-time no-TD rate is 0 and both stage-1
arms stake exactly zero on it. B2 zeroed 11 (the same five plus six
games where an early-season pool split was 0). V1 never zeroed a
realized player or DEF/ST outcome.

Calibration deciles (V1, stated vs realized): decile 1 (top)
0.0782/0.0598; 2: 0.0164/0.0262; 3: 0.0047/0.0129; 4: 0.0008/0.0011;
5–10 at or below 0.0004 stated. Only the top decile is a criterion;
the mid-decile understatement is recorded as an observation.

## Reading

The design's motivating claim — offences script early possessions
toward the red zone, so first-TD shares carry signal beyond
anytime shares — is falsified on this panel at the design's own
constants: first-TD counts to date are the noisier estimate
(≈5 team-first events per team-season-to-date vs ≈35 anytime
events), and shrinking them at K1 = 3 toward the anytime share
still leaves enough variance to cost 0.167 nats/game against the
anytime-share-only baseline, in every season. Against the bare
positional pool the player layer is a wash (−0.016, CI spanning
0). This mirrors the 2+ TD family's pool-domination finding: the
player-level layer, as specified, does not beat its own collapsed
form.

## State notes

- This screen ran on design data (2020–2025, the seasons the
  design was written against). Per the design section 0 it is an
  entry ticket only, never validation; the verdict here is
  terminal for V1 regardless.
- Canonical coverage continues to resolve this family NO_DATA:
  design steps 2–3 (forward capture artifacts) remain unbuilt,
  and the FAILED_SCREEN verdict removes the basis for building
  them for V1.
- `sportsedge/forward_validation/configs/nfl_first_td.json` is
  untouched and still `model_version: "UNPINNED"`. Nothing is
  frozen. The frozen anytime-TD family (v1.1) is untouched.
