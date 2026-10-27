# FREEZE RECORD — NBA Team Totals Forward Test V1

- Document: `research/nba_team_totals_forward_20261022/PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md`
  (path keeps its drafting name; its status lines read FROZEN)
- Final CLEARED draft sha256 (incl. zero-moved-rows clarification, commit `e31d03ed`):
  `4cf7e364a945c77ef316bfbd3bd04edf9ce51618e1eec5b6a16b9c354cc042e9`
- Frozen document sha256 (status lines + §12 ticks only):
  `0274e8cd248ed56a43c445c3d23e96e04eb218f4abcafb2ebe4041448ef55504`
- Independent re-review: CLEARED on `ec9adcfa61139f703a13c680f571b2dfc0fb1fd5`;
  the only later term-text change is the one clarification line in `e31d03ed`
  ("If there are zero moved picked rows, the sign test isn't run and rule 1 doesn't apply.").
- Freeze timestamp: **2026-10-23T02:34:21Z (UTC) = 2026-10-22 21:34:21 CDT (CT)**
- Authority: **rulings by Grok under owner delegation, message t234u, Oct 22 2026 9:32 PM CT**
- Bootstrap seed (§9): **20261022** (game-cluster bootstrap, 10,000 resamples)
- First counted slate: **first slate priced after the evaluator is pinned and reviewed**.
  No §6 primary metric is computed on any forward row before then.
- Engine pins (main @ ddf938894): `sportsedge/nba_team_period_engine.py`
  `9060b972f9d1f69696db7f75569ab175884e02ff7b6ea81fb9817c6f390bc6de`;
  `sportsedge/research/nfl_nba_engine_card_annex.py`
  `28edafba1e41baa4e0485d9c14542d4c8ba56d2a3913a8d22a546541fb13cbe2`.

## k — forward clocks whose counting windows overlap (recorded at freeze)

Resolved conservatively: a clock that is frozen, locked, or ruled to run
and may count rows during this test's window is included even if its
own counting has not started. A larger k only widens intervals.

| # | Clock ID | Source |
|---|---|---|
| 1 | NFL_PROPS_PART2_FORWARD_V1 | PR #2396 (`c1d76d76f`), research/nfl_props_part2_20261018/PREREG_NFL_PROPS_PART2_FORWARD_V1.md |
| 2 | NFL_PROPS_PART2B_FORWARD_V1 | PR #2415 (`d41688010`), research/nfl_props_part2b_20261020/PREREG_NFL_PROPS_PART2B_FORWARD_V1.md |
| 3 | NFL_PROPS_V1_1_MOVED_LINE_AMENDMENT | branch grok/nfl-props-v1-1-moved-line-amendment-20261022 (CLEARED; freeze due before Sun Oct 25 noon CT). Counted separately, conservatively. |
| 4 | NBA_PROPS_FORWARD_V1 | PR #2424 (`ae9588198`), research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md (sha256 54363908…) |
| 5 | NFL_TOTALS_LEVEL_V2_FORWARD | research/forward_validation_program_20261020/PROGRAM.md §1 (forward leg scores Jan 13, 2027) |
| 6 | MLB_PITCHER_PROP_PROMOTION_V2 (pitcher-K protocol) | docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md (v2, Oct 4 2026); PROGRAM.md §1 |
| 7 | NFL_ANYTIME_TD_FORWARD_V1 | PR #2399 (`b5dabb3be`), locked Oct 18; engine freeze held pending fixes (branch grok/t227-nfl-atd-engine-fixes-20261022) |
| 8 | NFL_PASSYDS_V2_FORWARD_SCREEN | branch grok/nfl-passyds-v2-prereg-focus-20261022 @ 7d6431ff; ruled to run (2026 wk 8+, 4 weeks) |
| 9 | NBA_TEAM_TOTALS_FORWARD_V1 | this document, from this freeze |

**k = 9** at freeze → α/k = 0.05/9 = 0.005556; intervals two-sided at
99.444%. Per §9, the list is re-recorded at review and the larger k is used.

Not counted (no overlapping forward clock): NBA game lines V1 (DRAFT,
not frozen), the 35 forward-validation program drafts (DRAFT), NBA totals
V2/V3 (historical screens; V3 failed), MLB benchmark v2 (one historical
scoring, not a forward clock), NBA period totals (not registered).
