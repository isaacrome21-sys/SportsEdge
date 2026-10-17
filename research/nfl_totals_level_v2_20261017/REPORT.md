# REPORT — NFL Totals LEVEL v2, Part A (diagnostic screen)

> **AMENDMENT 1 (governs). Read `DEVIATION_RECORD.md`.** The numbers in
> the body of this report are the **as-run** result. The as-run evaluator
> let season S−2 data into season-S predictions through the residual
> anchors, which breaks prereg §1. It was not lookahead. The conforming
> re-run (`results_nfl_totals_level_v2_part_a_amendment1.json`) is the
> governing result: **SCREEN_PASSED**, candidate **7.6342**; vs FROZEN
> −0.1883 [−0.2802, −0.1035]; vs B2 −0.0785 [−0.1498, −0.0053]; vs B3
> −0.1751 [−0.2412, −0.1065]; n = 1,887. A second independent verifier
> pass confirmed it at `17bed5e4`.

**Date:** Sat 2026-10-17 · **Label:** RESEARCH_EVIDENCE — DIAGNOSTIC
SCREEN on reused 2018–2025 development data. NOT out-of-sample
validation, NOT a market verdict, NOT a promotion input. Nothing is
wired; `WATCH_NFL_TOTAL_PRIOR_ONLY` is unchanged.

**Preregistration:** `PREREG_NFL_TOTALS_LEVEL_V2.md`, SHA-256
`8eddc0baa1185163ffcc8a7dcb895393e507a8e0ccac57e6f89b7f3ae6f3e78b`,
pushed to this branch at commit `9e94c10074a74b8ec0732f203bb6009276660af8`
(2026-10-17 04:34 CT) **before the evaluator existed or any v2 score
was computed**. The evaluator verifies the lock at load.

## SCREEN VERDICT: SCREEN_PASSED

All three preregistered legs pass (paired n = 1,887, identical to
Stage 2 and v1):

| Arm | Mean total CRPS |
|---|---|
| **Candidate — LEVEL v2** | **7.6345** |
| B2 — same-season climatology | 7.7126 |
| B3 — two-season climatology (new) | 7.8093 |
| FROZEN prior (as shipped) | 7.8225 |

| Leg | Paired ΔCRPS [95% CI] |
|---|---|
| vs FROZEN | −0.1880 [−0.2805, −0.1027] |
| vs B2 | **−0.0781 [−0.1496, −0.0048]** ← the tight leg |
| vs B3 | −0.1747 [−0.2405, −0.1061] |

For comparison, LEVEL v1 on the same frame: 7.7606, which lost to B2
(+0.0479).

**What this does and does not mean.** The construction that v1's
diagnosis pointed to, a faster level that carries across the
offseason, clears every baseline on the development data. That data
has now informed three NFL totals evaluations, so this is a screen,
not validation. Under the prereg it earns exactly one thing: **Part B,
the prospective test on 2026 games kicking off ≥ 2026-10-18 ET**,
scored once after the 2026 regular season ends. The B2 leg's upper
bound (−0.0048) is close to zero. Part B, with about 190 games, may
well come back INCONCLUSIVE, and the report will say so if it does.

## Per-season (ΔCRPS, negative = candidate better)

| Season | vs FROZEN | vs B2 | vs B3 |
|---|---|---|---|
| 2018 | −0.246 | −0.131 | −0.251 |
| 2019 | −0.279 | −0.162 | −0.229 |
| 2020 | −0.738 | −0.150 | −0.299 |
| 2021 | **+0.120** | **+0.090** | −0.077 |
| 2022 | −0.113 | −0.110 | −0.170 |
| 2023 | −0.041 | **+0.013** | −0.051 |
| 2024 | −0.095 | **+0.001** | −0.147 |
| 2025 | −0.158 | −0.189 | −0.191 |

There are no seasons where a CI sits entirely above zero against any
arm. The candidate's point estimate loses in 2021 (vs FROZEN and B2)
and roughly ties B2 in 2023–2024. These are named here, not averaged
away.

**Level tracking (v1's named defect):** per-season mean signed error
now spans −1.01 (2024) to +0.77 (2021). v1 spanned −2.13 to +2.67.
Residual sd is 13.61 against the fixed 13.5. OVER Brier at
{37.5…52.5}: the candidate is lowest at every line (e.g. 46.5: 0.2401
vs 0.2475 / 0.2480 / 0.2481).

## Verification performed before reporting

- **Reproduction precondition PASSED:** FROZEN 7.82248 and B2 7.71262,
  with Δ and CI matching Stage 2 within 1e-3. Population 2,127 scored /
  240 ineligible / 1,887 paired.
- **Corpus:** exact Stage 2 bytes (SHA-256 `a484c6ae…`), recovered from
  nflverse/nfldata commit `4c15d524` and verified at load. Line columns
  are never read.
- **Precondition environment check:** before v2 existed, v1's evaluator
  was re-run here and reproduced v1's published results JSON
  byte-for-byte except `generated_at`.
- **Unit checks:** `tests/test_nfl_totals_level_v2.py`, 8/8. They were
  run locally with a minimal pytest stand-in because the sandbox has no
  PyPI access; hosted CI is the arbiter.
- **Independent hand check** (`handcheck_v2.py`, which does not import
  the candidate module and uses a different traversal): 14 fixtures,
  max |Δ| 4.5e-10, limited by the audit's 1e-9 rounding.
- **No-lookahead teeth:** adding +50 to every game at or after a
  fixture's kickoff leaves its prediction unchanged on all 14. The
  control (corrupting the latest strictly-prior team game) moves it on
  all 14.
- **Determinism:** a second run reproduces the results JSON except
  `generated_at`.
- **Audit CSV:** 2,127 rows, SHA-256 `a7ee2c0d…bf1`. It is regenerated
  by the evaluator's `--audit` flag and is not committed (transport
  size).
- **Independent verifier:** VERIFIED the as-run result at `c1753443`, and
  VERIFIED Amendment 1 at `17bed5e4`. Both re-runs were from fresh clones.

## Reproduce

```
# corpus: git -C nfldata show 4c15d52430866a57c1e7118177d8aea2e0905ab0:data/games.csv > games.csv
python3 research/nfl_totals_level_v2_20261017/eval_nfl_totals_level_v2.py \
  --dataset games.csv --out results.json --audit audit.csv
python3 research/nfl_totals_level_v2_20261017/handcheck_v2.py games.csv audit.csv
```

## Next

Part B runs after the final 2026 REG game. Nothing is scored before
then. No market leg exists for this family until a separate
preregistration, written only if Part B passes. PLAY is not in reach
from this result alone.
