# SCREEN REPORT — `NFL_RUSH_REC_PROPS_V1` — **SCREEN_FAIL on all three markets**

One declared run, Wed Oct 28, 2026, 10:12 PM CT, under `BUILD_RECORD.md`
(committed first, `c8bef924`) and the construction/screen code committed
before the run (`55cfa6ac`). Machine-readable output: `screen_results_v1.json`.
Bootstrap seed used: **20261028** (explicit override, F3). Integrity checks
(R12: hashes, evaluator hash, loader parity, prior alignment, INC arm = the
incumbent's own `evaluate()` n and CRPS) all passed; 0 unpriceable rows.

| Market | n | CRPS M / INC / B1 / B2 | Δ vs INC [95% CI] | Gaps M top/bottom vs INC top/bottom | Legs 1/2/3/4 | Verdict |
|---|---|---|---|---|---|---|
| RUSH_YDS | 3,226 | 19.2816 / 19.4599 / 20.8315 / 20.9256 | −0.1783 [−0.2582, −0.1014] | 0.0985 / 0.0075 vs 0.0676 / 0.0108 | ✔ ✔ ✘ ✔ | **SCREEN_FAIL** |
| REC_YDS | 8,278 | 18.2739 / 18.3096 / 19.6496 / 20.0359 | −0.0358 [−0.0854, +0.0119] | 0.0830 / 0.0537 vs 0.1091 / 0.0298 | ✘ ✔ ✘ ✔ | **SCREEN_FAIL** |
| RECEPTIONS | 8,278 | 1.2759 / 1.2806 / 1.3786 / 1.3996 | −0.0047 [−0.0090, −0.0006] | 0.0973 / 0.0026 vs 0.0939 / 0.0295 | ✔ ✔ ✘ ✔ | **SCREEN_FAIL** |

Fitted constants (2018–2019 only): r_N = 11.0103 (carries), 15.4628
(targets); σ² = 48.4476 (rush), 115.4277 (rec).

**Reading.** M beats both baselines everywhere and beats the incumbent's
CRPS outright on RUSH_YDS and RECEPTIONS, but the claim's own leg (3)
fails in every market: M's top-decile gap stays above 0.05 (0.0985,
0.0830, 0.0973), and on RUSH_YDS and RECEPTIONS it is larger than the
incumbent's. The overconfidence on the strongest over calls was not fixed.
REC_YDS also fails leg 1 (CI upper +0.0119).

**Effect (design §5):** construction FAILED_SCREEN and retired for all
three markets. No retune, re-bucketing, or constant change. The incumbent
(Part 2) and its frozen forward test are untouched. No freeze, adoption,
or market claim.

F4 note: n here is on the B8 file set (3,226 / 8,278 / 8,278); the Oct 17
published incumbent figures (3,217 / 8,264) came from the pre-B8 file.
