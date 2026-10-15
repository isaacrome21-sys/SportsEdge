# Reproduce — M2 (run line) and M4 (totals) verdicts

Everything needed is in this repository on branch
`research/mlb-market-legs-20261014` **except the corpus itself**, which
is third-party data under no granted license and is therefore not
committed (see `DATASET_MANIFEST.md` — stated plainly there and here:
**the SBR corpus is NOT in this repo**).

## Step 0 — acquire and verify the corpus

Download `mlb_odds_dataset.json` from the GitHub repository
`ArnavSaraogi/mlb-odds-scraper`, release tag `dataset` (asset of the
same name), then verify:

```
sha256sum mlb_odds_dataset.json
# must print:
# 3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b
```

A different hash means a different dataset; the verdicts do not
transfer. Both evaluators re-verify this hash at load and refuse to
score a mismatched file.

## Step 1 — verification precondition (M1 reproduction)

From the root of a checkout of this branch:

```
python3 scripts/eval_mlb_lane_a_vs_close.py \
  --dataset /path/to/mlb_odds_dataset.json \
  --out /tmp/m1_repro_results.json --audit /tmp/m1_repro_audit.csv
```

Expected: matched n = 10,237; Brier model 0.247856 / market 0.236332;
ΔBrier +0.011523 [+0.007548, +0.016433]; verdict DOES_NOT_BEAT_MARKET —
an exact reproduction of the M1 moneyline evaluation (see
`M1_REPRODUCTION_NOTE.md`). This proves the Lane A means at this
branch's base commit (`2a713380c7d49733577c238a126f487382634040`) are
the M1 means.

## Step 2 — M2 run line

```
python3 scripts/eval_mlb_runline_vs_close.py \
  --dataset /path/to/mlb_odds_dataset.json \
  --out mlb_market_legs_20261014/results_m2_runline.json \
  --audit mlb_market_legs_20261014/audit_m2_runline.csv \
  --m1-audit /tmp/m1_repro_audit.csv
```

(`--m1-audit` is optional; it only fills the matched-subset overlap
count.) Expected: verdict **DOES_NOT_BEAT_MARKET**, n = 10,237,
25/25 calculate() parity checks, output identical to the committed
results JSON except `generated_at`. Spec: `SPEC_M2_RUNLINE.md`
(SHA-256 `68c7020fef4df5bb9ab132dcf43b652b4ffcb57cff92e49cde30949e780785b6`,
hashed before scoring — see `SPEC_HASHES.txt`).

## Step 3 — M4 totals

```
python3 scripts/eval_mlb_totals_vs_close.py \
  --dataset /path/to/mlb_odds_dataset.json \
  --out mlb_market_legs_20261014/results_m4_totals.json \
  --audit mlb_market_legs_20261014/audit_m4_totals.csv \
  --m1-audit /tmp/m1_repro_audit.csv
```

Expected: verdict **DOES_NOT_BEAT_MARKET**, matched-with-total
10,239, push-outcome exclusions 286, scored n = 9,953, 25/25 parity
checks, output identical to the committed results JSON except
`generated_at`. Spec: `SPEC_M4_TOTALS.md`
(SHA-256 `fd644387d84eb243febe63276321c5d6cbd525bbe7aa3e73c6008cd99e347c56`).

## Environment

Python 3 standard library only. The evaluators load
`artifacts/free_models.py` from the checkout they live in — run them
from this branch's tree so the pinned model is the one scored.

## What is committed, and what is not — plainly

Committed on this branch: the two specs, the dataset manifest, the
spec hashes, the M1 reproduction note and its results, the three
evaluator scripts, and the two results JSONs (the verdict record).
**Not committed: the per-game audit CSVs** (`audit_m2_runline.csv`,
2.1 MB; `audit_m4_totals.csv`, 2.3 MB). They are deterministic
outputs of the Step 2/3 commands above — the evaluators were verified
to reproduce their results JSONs exactly on re-run — so they are
regenerable from the repo + corpus alone; the workspace copies are
held in the lane folder (`~/workspace/sportsedge/
mlb_market_legs_20261014/results/`). One sentence in
`DATASET_MANIFEST.md` ("the per-game audit CSVs and results JSONs
under `mlb_market_legs_20261014/`") was written before this
disposition was set; the manifest is a hash-locked spec-bundle file
and is therefore corrected here rather than edited: read it as
"the results JSONs under `mlb_market_legs_20261014/`; the audit CSVs
regenerate from the documented commands."
