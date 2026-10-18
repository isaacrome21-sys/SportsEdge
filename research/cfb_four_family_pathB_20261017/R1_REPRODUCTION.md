# R1 independent reproduction: designated provider Bovada

R1 (freeze package §4) designates Bovada as the descriptive-only lines comparator, based on a
per-provider coverage table. `r1_independent.py` re-derives that table from the pinned archive
(`cfb_line_odds.csv.gz`, SHA-256 `7ae899d9…8d4d`, blob `fe568cf1…`). It imports nothing from the
repo and is written from the rule text alone:

- sides keyed by school name from `game_desc`;
- spread rows must mirror;
- total rows must agree;
- moneyline cross-checked against a nonzero spread's favorite, with unchecked pairs quarantined.

Result for seasons 2021–2025 (the scored folds), `r1_result_2021_2025.json`:

| Provider | Any market | ML ok | ML quarantined | Spread ok | Total ok |
|---|---|---|---|---|---|
| Bovada | 4,325 | 3,588 | 220 | 4,324 | 4,323 |
| ESPN Bet | 3,541 | 1,524 | 68 | 3,529 | 3,532 |
| William Hill (NJ) | 3,105 | 0 | 0 | 3,105 | 3,103 |
| DraftKings | 2,379 | 2,128 | 122 | 2,370 | 2,259 |

This is **identical to the freeze package's R1 table on every cell.** Bovada is the largest
single-book coverage on every market. R1 is reproduced.

Under Path B (regular season only) the matched counts are smaller but still clear every floor.
Per `pathB_dry_restatement_results.json`: pooled ML 3,210 and spread/total 3,567, against a
2,500 pooled floor.

**Remaining before Attempt 1 (ruling 3):**
1. Immutable freeze identity. The freeze package must be restated for Path B, filed, and the
   freeze SHA named at the freeze commit (the owner's freeze act).
2. An exact-head all-green hosted CI run.
3. Isaac's separate execution GO.

Attempt 1 is not consumed.
