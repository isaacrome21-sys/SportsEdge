# D2 Reconciliation — Pitcher B2 (League Baseline) Outs CRPS: 2.1705 vs 2.0267

**Flag:** D2 in `~/workspace/sportsedge/shrinkage_adoption_records_20261015/RECORDS.md`
**Date:** Oct 15–16, 2026 · **Scope:** evidence only — no code changes, no repo writes.

---

## Verdict

**Under the preregistered B2 definition, the correct value is 2.1705.**
**2.0267 could not be reproduced from any artifact that exists** — no code,
no results file, in the workspace or in any git ref. The two lanes were
measuring different quantities under the same name, and only one of the two
quantities is identifiable: the fix lane's. The 2.0267 figure survives solely
as a number quoted inside a background completion message (relayed in the
fix lane's `REPORT.md`, flag 2) for a run that left no persistent artifact.
It should not be relied on, and it does not contest 2.1705.

---

## 1. The preregistered definition (quoted)

`model_fix_20261014/specs/PREREG_PITCHER_UNDERCARD.md` (SHA-256
`9628b962…a41c`, verified against `SPEC_HASHES.txt`):

- §3: *"League distribution L_m(d) = pooled empirical distribution over
  all starters' prior starts in the season to date — identical
  construction to Phase 2's B2."*
- §3: *"CRPS computed under the identical support/truncation convention
  the Phase 2 evaluator applied to B1/B2 (the implementing code is reused
  or mirrored exactly…)"* — restated in the evaluator and results JSON as:
  **CRPS = Σ over m = 0..crps_m_max of (F(m) − 1{y ≤ m})² with
  F(m) = 1 − p_over(m+0.5)**; for Outs, m = 0..27.
- §5, arm 4: *"B2 — league climatology."*

Implementation (`model_fix_20261014/scripts/eval_challenger_pitcher_undercard.py`):
`build_population` accumulates every parsed start (gamesStarted == 1) into
per-market counters in date order and snapshots the counters for each
fixture using only events with `date < fixture date` — expanding,
strictly-prior, all starters including the fixture pitcher's own prior
starts. CRPS at `crps_from_cdf` / `emp_cdf_getter` (lines 241–275).

## 2. 2.1705 — reproduced three independent ways

1. **Recorded results:** `model_fix_20261014/results/challenger_pitcher_undercard_results.json`
   — Outs: FROZEN 2.1392 / CHALL 2.0512 / B1 2.1163 / **B2 2.1705**, n = 3,382.
2. **Full evaluator re-run** (this reconciliation): the lane's own script,
   `eval_challenger_pitcher_undercard.py score`, run from its own scripts
   against its own cache (`~/workspace/tmp/bt_data/statsapi_cache`,
   acquisition manifest `ACQUISITION_2026_DONE.json`), wrote a scratch
   results file whose headline line is byte-for-value identical:
   `OUTS ADOPT-CANDIDATE n=3382 ch 2.0512 fr 2.1392 b1 2.1163 b2 2.1705`
   (all four markets reproduced, incl. HA B2 1.2507, BB B2 0.7003).
3. **Independent recomputation** (this reconciliation): a separate script
   re-derived fixtures and the expanding league counters from the raw
   cache and recomputed the step-sum CRPS — **V0 = 2.1705** on the same
   3,382 fixtures. The identity-form CRPS (E|X−y| − ½E|X−X′|) on the same
   pools also gives 2.1705, so the CRPS *form* is not a free variable here.

## 3. 2.0267 — provenance search (negative)

- The string `2.0267` appears in exactly two prose sources, both on the
  fix-lane side: `model_fix_20261014/REPORT.md:55` and `RECORDS.md:312`.
  The REPORT's own wording: *"Child A received background completion
  messages for runs it did not execute: a batter run passing only Walks,
  and a pitcher run failing all four markets with B2 Outs CRPS 2.0267 vs
  this lane's 2.1705 — same fixture counts (38,511 / 3,382)…"*
- **Workspace:** full-text search of `~/workspace/sportsedge/` — no owner-lane
  pitcher results JSON, script, or report contains the value (all other
  hits are coincidental substrings in market-data/Statcast dumps; the
  F5 results' `crps_marg: 2.02677…` is a different quantity — an F5
  marginal — not a pitcher B2).
- **Repo:** `git grep` for `2.0267` across **every** local and remote ref
  (`*.py`, `*.md`, `*.json`) — every hit is a coincidental substring:
  rows inside `tests/fixtures/savant/statcast_slice_20261005_20261008.csv`
  (pitch data), and `"weight": 2.0267868878733213e-09` fields inside NFL
  V2G prospective-prediction JSONs on the `data` branch. No MLB
  evaluation artifact in any branch contains the value as a CRPS.
- **The three owner draft PR branches contain no pitcher-CRPS code at all:**
  - #2311 → `research/mlb-batter-shrinkage-challenger-20261014` adds
    `research/mlb_batter_shrinkage_challenger.py` — a binary
    shrinkage-probability comparator scored by **log loss only**.
  - #2312 → `research/mlb-batter-trailing-baseline-20261014` adds
    `research/mlb_trailing_baseline.py` — binary trailing baseline vs a
    constant league prior, **log loss only**; its "league" is a scalar
    prior (default 0.5), not a distribution.
  - #2314 → `research/mlb-paired-evaluation-harness-20261014` adds
    `research/mlb_paired_evaluation.py` — a paired **binary** evaluator
    (log loss + Brier); it validates supplied probability records and
    states it *"cannot prove provenance."*
  
  None of the three implements CRPS, a count distribution, or a pitcher
  pool. Whatever produced 2.0267, it was not the code in these PRs, and
  it was never committed.

## 4. Single-ingredient toggles on the identical fixture set (n = 3,382)

Each variant changes exactly one ingredient of the preregistered
construction, holding fixtures, outcomes, and the step-sum CRPS fixed
(except where the toggle *is* the CRPS form). Target: 2.0267
(gap from 2.1705: −0.1438, −6.6%).

| # | Toggle | B2 Outs CRPS |
|---|---|---|
| V0 | Preregistered construction (control) | **2.1705** |
| V1 | League pool = full-2026-season static pool (in-sample, incl. future starts) | 2.1803 |
| V1b | Full-season pool, leave-own-game-out | 2.1812 |
| V2 | Expanding pool incl. same-date starts (`date ≤ d`, incl. own game) | 2.1686 |
| V3 | Expanding pool excluding the fixture pitcher's own prior starts | 2.1725 |
| V4 | Identity-form CRPS (E\|X−y\| − ½E\|X−X′\|) on prereg pools | 2.1705 |
| V7 | League pool = trailing-60-day window only | 2.1711 |
| V8 | League pool = repo `config/mlb_pitcher_prior_league_short_2026.json` (502-start few-starts pool) | 3.7832 |
| V9 | Expanding pool initialized with all 9,704 cached 2024+2025 starts | 2.1540 |
| V10 | League pool = each pitcher's trailing ≤12 starts only | 2.1898 |
| V11 | CRPS index shifts (CDF/indicator off-by-one family, 9 combos) | 2.1705 – 2.6578 |
| V12 | Naive outs conversion `int(float(IP)×3)` applied to pools + outcomes | 2.2454 |
| — | Summary statistic: median of per-fixture CRPS instead of mean | 1.3222 |
| — | Subset: April fixtures only / May+ only | 2.0904 (n=131) / 2.1737 (n=3,251) |

**No toggle reaches 2.0267; the closest (V9) is still 0.127 away, and
every PIT-leakage toggle moves the value the wrong way.** Notably, the
fix lane REPORT's own conjecture — *"if its league distribution was
built full-season (in-sample), it would not be a valid PIT baseline"* —
is tested by V1 and **fails as an explanation**: on these fixtures a
full-season pool scores *worse* (2.1803), not better. For reference,
Phase 2's B2 Outs on its own splits (backtest program results JSON):
pooled 2024–25 = 2.0540, 2024 = 2.0824, 2025 = 2.0375 — none equals
2.0267 either, so it is not a stray Phase 2 number.

## 5. Conclusion

- **Which value is correct under the preregistered B2 definition:**
  **2.1705** — preregistered construction (§3/§5 above), reproduced from
  the lane's scripts, from its recorded results, and from an independent
  recomputation off the raw cache.
- **What 2.0267 is:** an unattributable figure from an unpersisted run.
  No single-ingredient deviation from the preregistered construction —
  pool window, pool membership, PIT cutoff, CRPS form, index convention,
  outcome conversion, summary statistic, or scoring subset — transforms
  2.1705 into 2.0267 on the same fixtures. The two numbers were therefore
  **not the same quantity**: at least one load-bearing ingredient of the
  2.0267 computation differed in a way that cannot be isolated because
  the computation itself no longer exists in any checkable form.
- **Recommendation carried by this record:** rely on 2.1705 (and the
  pitcher family's gate verdicts that stand on it); treat 2.0267 as
  withdrawn-by-unverifiability. If the owner lane wants its figure
  reconsidered, the burden is a persisted evaluator + results file —
  the standard the fix lane's set already meets.

*Method note: all recomputations ran against the fix lane's frozen
StatsAPI cache with `TMPDIR=~/workspace/tmp`; variant scripts were kept
out of the repo (scratch only). The evaluator re-run wrote to a scratch
output path; the lane's recorded results JSON was not modified.*
