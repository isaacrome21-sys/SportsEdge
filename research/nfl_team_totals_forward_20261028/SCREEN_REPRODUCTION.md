# SCREEN REPRODUCTION — NFL_TEAM_TOTAL_DIST_V1 with the BUILT engine

**Run:** Oct 28, 2026, harness `reproduce_screen_with_engine.py` in this
package, driving the committed engine `sportsedge/nfl_team_total_dist.py`
— not the design script of the activation pack. Full machine output:
`screen_reproduction_results.json`. Design reference:
`DESIGN_SCREEN_RESULTS_REFERENCE.json` (verbatim copy of the design
run's own output, draft PR #2852).

**Status: DESIGN SCREEN REPRODUCTION — an entry ticket, never
validation.** Every season screened is DESIGN data (seen by retired
constructions). No market verdict is issued or implied.

## Input identity

| Input | sha256 | Note |
|---|---|---|
| nflverse schedules `games.csv.gz` | `1b4ca0c70eea4236bf35eda85a04746ce031cafbafa962dfc7cc9572166535ec` | 7,548 rows, 515,931 bytes — **byte-identical to the design screen's pull** (same hash the activation pack recorded). The rolling-asset drift the pack disclosed did not recur for this pull. |

## Result: the built engine reproduces the design screen EXACTLY

Every reported number — pooled and per-season, MAE / CRPS / PIT /
inside-90% / implied-split diagnostic, and the training constant c —
matches the design run with **delta exactly 0.0**. Nothing was tuned:
the engine was implemented from the design spec, run once against the
pre-committed criteria, and landed on the design's numbers bit-for-bit.

- Pooled CV from the 2018–2019 training seasons: c = 0.46438741207903494
  (design: identical).
- Pooled 2020–2025, n = 3,230 team-games:

| Metric | Candidate | B1 team mean | B2 league mean | Implied split (design diagnostic) |
|---|---|---|---|---|
| MAE | **7.749** | 7.831 | 7.924 | 7.250 |
| CRPS | **5.528** | 5.590 | 5.625 | — |

- Calibration: PIT mean 0.537; 91.0% of realized scores inside the
  central 90% interval.
- Per season (MAE candidate / B1 / B2 / implied; CRPS candidate / B1 / B2):

| Season | n | MAE | CRPS |
|---|---|---|---|
| 2020 | 512 | 7.838 / 7.891 / 7.932 / 7.284 | 5.637 / 5.710 / 5.663 |
| 2021 | 544 | 8.205 / 8.211 / 8.438 / 7.663 | 5.826 / 5.833 / 5.904 |
| 2022 | 542 | 7.253 / 7.427 / 7.434 / 6.915 | 5.183 / 5.268 / 5.283 |
| 2023 | 544 | 7.749 / 7.825 / 7.918 / 7.318 | 5.537 / 5.606 / 5.624 |
| 2024 | 544 | 7.787 / 7.767 / 7.864 / 7.075 | 5.490 / 5.507 / 5.583 |
| 2025 | 544 | 7.667 / 7.865 / 7.954 / 7.247 | 5.500 / 5.622 / 5.691 |

- **Screen verdict under the criteria fixed before the design run**
  (pooled MAE < B1 and < B2 AND pooled CRPS < B1 and < B2 AND no season
  worse than its B2 by more than 0.25): **PASS** — the same verdict the
  design script recorded.

## Disclosure (carried forward verbatim from the design screen report)

**Disclosure, in the open (the NBA team-totals §0 pattern):** the
candidate beats the naive baselines it was screened against — narrowly
(≈0.08 MAE pooled) — and **loses clearly to the market's implied split**
(7.749 vs 7.250). The forward test's governing leg is accuracy against
the DraftKings closing team-total line, and on this design evidence
that leg is the expected-risk leg: the DK team-total line is not a
naive (total ∓ spread)/2 split of a stale total — it is a traded line
informed by the closing spread and total, which are themselves sharp.
The construction advances to ARMED-pending-freeze because the screen it
was given asked about the naive baselines and it passed, and because
the forward test — not this screen — is where the market question is
answered, with the moved-row and CLV legs measuring something MAE
against a snapshot cannot. Anyone reading this pass as market evidence
is misreading it.
