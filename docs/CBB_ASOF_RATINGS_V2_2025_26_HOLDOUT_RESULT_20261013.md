# Result: CBB as-of ratings v2, fresh-season holdout on 2025-26: PASS_RESEARCH

**Provenance**
- Pre-registration: `CBB_ASOF_RATINGS_V2_2025_26_HOLDOUT_PREREG_20261013.md` (`5bd7b72`), committed before the fetch.
- Code: frozen at `a19f7d7`. The prereg commit is the only diff.
- Command: `PYTHONPATH=. python scripts/run_cbb_asof_harness.py /workspace/cbb_cache_2025_26 v2 d1`.
- Research only. Lines are NAIVE_STANDIN. **The market baseline stays MISSING.** No PLAY is produced.

**Data**
- Free ESPN; 6,195 completed events, 0 fetch errors. 6,194 loaded and 19 skipped as invalid.
- The cache is outside the repo.
- Minor deviation: the fetch loop also requested 2026-03-16, one day past the pre-registered end date. It returned **0 events**, so there is no effect.

**Population**
- 4,398 D1-vs-D1 scored games; 4,397 for totals after pushes.
- Excluded from evaluation, and used in training only: 554 games involving a non-D1 team and 381 Illinois games (by ESPN ID).

| market | n | model Brier | naive Brier | model log-loss | naive log-loss | 2024-25 model Brier |
|---|---|---|---|---|---|---|
| moneyline | 4398 | **0.1991** | 0.2509 | **0.5788** | 0.7020 | 0.1941 |
| spread (stand-in) | 4398 | **0.2417** | 0.2500 | **0.6762** | 0.6931 | 0.2384 |
| total (stand-in) | 4397 | **0.2477** | 0.2500 | **0.6886** | 0.6931 | 0.2443 |

The joint home-court estimate at season end is **H = 4.55**; it was 4.69 in 2024-25.

**Decision: PASS_RESEARCH.** The model beats naive on all three Brier scores and on moneyline log-loss.

## Honest reading
- **First unexamined-season evidence for v2.** The edge over naive held, but it shrank somewhat compared with 2024-25 on every market, as expected out of sample.
- **The total-market edge is thin**: 0.0023 Brier against a 0.25 coin-flip stand-in.
- **The lines are naive stand-ins.** This is not evidence of an edge against DK; paired, timestamped closing lines are still required.
- **D1 membership comes from the 2026 directory.** That is identity only, but it is not an as-of directory.
- **Home court is still high** at about 4.5, versus a typical 3–3.5.
- Research only. No promotion. The Illinois exclusion was enforced by ESPN ID.
