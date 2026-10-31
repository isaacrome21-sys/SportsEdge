# Research record — Oct 31, 2026 (Claude lane): CFB model vs 2025 closes; NFL prop over/under calibration

**Records only. Research, not validation.** Nothing frozen, adopted, or counted changes. Run in a scratch environment on public SportsDataverse / nflverse release files, not the pinned repo data sets; figures are this run's, not repo-verified. Scripts in `scripts/` use scratch inputs and are kept for reproducibility of method, not as runnable repo tools.

## 1. CFB_GAME_EPA_JOINT_V1 construction vs ESPN closing lines, 2025 (design data)

Walk-forward, weekly snapshots (2024 season as prior, 24h embargo), `predict_fixture` from `sportsedge/cfb_game_epa_joint_v1.py` at the #2971 head `6d285cf` (pre-amendment, `ADJUSTMENT_MAX_ITERATIONS = 500`). Weeks 5+, games with an ESPN close: n = 558.

| | Margin MAE | Total MAE |
|---|---|---|
| Construction | 12.75 | 14.16 |
| ESPN close | 11.84 | 12.21 |
| PM baseline | 13.47 | 13.46 |

ATS hit rate by |model − close|: 0–2: .547 (172, inside noise), 2–4: .473 (131), 4–7: .493, 7–12: .451, 12+: .500 (20). O/U: 0–2: .519, 2–4: .467, 4–7: .600 (115), 7–12: .486, 12+: .413 (92). Totals biased +1.8 high. Blending close + k·(model − close) worsens MAE at every k in {0.1, 0.2, 0.3, 0.5}.

Operational finding (at the 500 cap): weeks 3–4 of 2025 raised `OPPONENT_ADJUSTMENT_NOT_CONVERGED` (epa_play). **Superseded by the owner-ruled amendment:** the #2971 head `1a7a0d3` raises the cap to 20000 (FREEZE_RECORD §7), under which those 2025 weeks converge (week 3 needs between 3,500 and 4,500 iterations). The "lane would emit nothing in those weeks" consequence applies only to the pre-amendment head.

Quick ridge points/EPA challengers (6 settings) also failed to beat the close (best: totals O/U 52.2% at a 2+ pt edge, selected post hoc).

## 2. Pre-written CFB market angles, 2024–2025 ESPN closes (FBS v FBS)

Dogs +20 or more cover: .545 / .530 (pooled .538, n = 238). Under when total ≥ 60: .587 / .527 (pooled .559, n = 202). Other angles ≤ .527 or unstable. Leads only (±6–7% margin of error); a forward watchlist, not a prereg.

## 3. NFL prop over/under calibration (Part 2 evaluator math + nfl_prop_engines_v1), near-even lines

Proxy lines at the player's projection ±15%; "miss" = actual over rate − priced over rate for p in (0.35, 0.65).

| Market | 2025 | 2026 (wk 1–7) |
|---|---|---|
| PASS_YDS | +.030 | +.093 |
| RUSH_YDS | +.044 | +.041 |
| REC_YDS | −.001 | +.004 |
| RECEPTIONS | −.041 | −.011 |
| pass+rush yds | +.029 | +.055 |
| rush+rec yds | +.012 | +.040 |
| targets | −.036 | −.019 |
| tackles+assists | −.024 | −.033 |

A 2025-fitted shift improves 2026 Brier for PASS_YDS (.2365 → .2318) and RUSH_YDS (.2499 → .2482), but **worsens** RECEPTIONS (.2456 → .2464). Reading: the reported "under bias" is the yardage engines under-pricing overs; count stats (targets, tackles) lean the other way. Suggested follow-up: a governed calibration amendment as its own prereg; nothing here edits the frozen Part 2 pricer.

Side note: the frozen Part 2 pricer refuses any data directory whose ps_/sp_ file set differs from SPEC_HASHES, so it runs only from the lane's pinned store (as intended).
