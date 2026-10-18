# NFL props calibration screen v1: result (RESEARCH_EVIDENCE, calibration only)

Prereg `bef8d74e…a148` locked at `60f53739` before any scoring. Data: nflverse weekly player stats
2018–2025 (hashes in SPEC_HASHES.txt). Trained on 2018–2019 (one constant per market); scored
2020–2025, weeks 4+. Determinism: byte-identical reruns (result `24637910…b332`). The independent
hand check reproduces the PASS_YDS population (2,360) and B1 CRPS exactly.

| Market | n | CRPS: candidate / player history / league role | Δ vs player history (95% CI) | Δ vs league role (95% CI) | Verdict |
|---|---|---|---|---|---|
| Passing yards | 2,360 | **45.63** / 49.47 / 47.32 | −3.84 [−4.69, −3.04] | −1.68 [−2.39, −1.01] | CALIBRATED_CANDIDATE |
| Rushing yards | 3,217 | **19.46** / 20.84 / 20.92 | −1.38 [−1.63, −1.13] | −1.45 [−1.71, −1.19] | CALIBRATED_CANDIDATE |
| Receiving yards | 8,264 | **18.33** / 19.67 / 20.05 | −1.34 [−1.55, −1.15] | −1.73 [−1.87, −1.58] | CALIBRATED_CANDIDATE |
| Receptions | 8,264 | **1.282** / 1.380 / 1.401 | −0.098 [−0.115, −0.083] | −0.119 [−0.131, −0.107] | CALIBRATED_CANDIDATE |

**Calibration at a line proxy** (each player's own prior median, rounded to x.5): the model's
over-probability tracks the realized over-rate within a few points in the middle deciles. It is
**overconfident in its most extreme decile**, most clearly on receiving yards (says 71%, realized
60%) and receptions (63% vs 54%). Any forward use must treat the model's strongest calls with
suspicion.

**What this means.** This model is realistic enough to be forward-tested against real DraftKings
prop prices. That is all. It cannot show an edge: no free historical prop prices exist. Next step
(Part 2): capture two-sided DK props for the full slate, de-vig, record the model's probability at
capture time, and score after a preregistered sample. No PLAY until that forward test passes.
