# Reproduction — CFB QB family (Isaac, Oct 17 2026: "Finish CFB")

**Status:** reproduction record only. Not a certification and not an adoption. The hold stays.

## What was run
- The committed `scripts/eval_challenger_cfb_qb.py` (head `cd5b668c`) was run on evaluand worktree `2a713380c`.
- Data: staging run **39070915985** of `cfb-espn-history` (PR #2379). It is COMPLETE for 2022, 2023 and 2024, with zero fetch failures and a summary for every completed game: 896, 911 and 919 summaries respectively, plus 703 passer gamelogs for 2024. It is labeled `ACQUIRED_POSTHOC_FROM_PUBLIC_ESPN`; never a pregame snapshot or a #2344 original.
- Raw data is unfiltered. The evaluator applied its own Illinois exclusion: 74 fixtures, the same count as the original.

## Deviations (stated before comparing)
1. **FBS 2024 list.** The original list (NCAA.com-derived) came from a script that is in no branch. This run used ESPN's 2024 FBS group, which has 144 ids. The 10 placeholder ids that never play a 2024 game were dropped, leaving **134**, the same count as the original.
2. **Collins gate skipped.** Its prior-game records file is in no branch. Builder identity is instead checked by hash inside the evaluator.
3. **Assembly audit.** The 10-fixture audit read the staged 2024 gamelogs instead of making a live fetch.
4. **Corpus.** The game corpus is ESPN groups=80 regular season plus postseason, refetched now. The original's exact file set is unknown.

## Result
| | Original | Reproduction |
|---|---|---|
| Verdict | ADOPT-CANDIDATE | **ADOPT-CANDIDATE** |
| Candidates | 1,695 | 1,695 |
| Scored | 417 | 424 |
| CRPS frozen / challenger / B1 / B2 | 47.82 / 44.34 / 47.78 / 44.92 | 47.89 / 44.55 / 47.90 / 45.13 |
| CI challenger − frozen | [−4.86, −2.14] | [−4.67, −2.04] |
| CI challenger − B1 | [−4.78, −2.06] | [−4.66, −2.04] |
| CI challenger − B2 | [−0.97, −0.17] | [−0.97, −0.20] |
| Assembly audit | 10/10 | 10/10 |
| Leakage tripwire | 10/10 | 10/10 |

- Every confidence interval is entirely below zero in both runs, so the verdict reproduces.
- The original scored 417 fixtures and this run 424. In the reproduction, 12 fewer fixtures were ROLE_NOT_MATERIALIZED and a new category, INSUFFICIENT_PIT_HISTORY, took 5. The likely cause is corpus differences (deviation 4); this was not investigated further.
- So the numbers agree closely but **not exactly**, unlike the MLB families.

With the pitcher and batter records, every #2368 family now has an independent reproduction. Certification and any hold lift remain Isaac's call.
