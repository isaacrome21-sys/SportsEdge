# October 25 postgame calibration: reproducible acceptance criteria

Status: RESEARCH ONLY. Owner-reported results are not independently authenticated graded rows.

## Input integrity
- Freeze raw prediction records with immutable event, sport, market, offer ID, side, line, American odds, captured_at, event_start, model version, feature as-of timestamp, stake, card ID and selection ID.
- Deduplicate by stable wager identity, retaining distinct card membership without double counting. Reconcile win/loss/push/void/pending and unit arithmetic against signed odds; reject unknown or contradictory settlements.
- Capture age <=150 seconds: eligible for research pricing; >150 to <=300: explicitly research-aged and non-actionable; >300 or future-dated: refused with no EV or model probability. Entry and closing snapshots must be separate, ordered and before event start. No backfill.

## Chronological replay
- Group split by event start; train/calibrate only on strictly earlier completed events. Preserve frozen model hashes and source as-of timestamps. Compare against contemporaneous no-vig market baseline.
- Report per SPORT:MARKET: sample size, Brier score, log loss, calibration slope/intercept, reliability bins, mean no-vig CLV, realized ROI and bootstrap intervals clustered by game/date. Report missing-engine/data blocker instead of fabricated metrics.
- Star and OC bucket results are descriptive only until held-out testing; avoid post-hoc tier inversions.

## NFL diagnosis
- Separate headline and all-priced cards; analyze underdog bias, spread/total/ML/prop slices, model-vs-market deltas and correlation/duplicate exposures.

## NBA diagnosis
- Separate team totals from game totals. Audit possessions, pace, lineup minutes, injury effective time, offensive/defensive matchup and team-total covariance. Compare MAE and probability calibration on held-out games.

## DFS diagnosis
- Reconcile DraftKings salary, eligibility, scoring and actuals by roster slot. Evaluate positional bias, availability, minutes/snaps, injury uncertainty, lineup correlation, ownership and distributional floor/median/ceiling. Backtest top-3 cash objective on historical contest slates; do not optimize on Oct 25 finals.

## Promotion constraints
- Six sports MLB/NFL/CFB/NBA/NHL/CBB; every market needs priced path or exact missing-engine/data blocker. Illinois-college exclusion, -165 straight-line cap, CFB production weight 0%. Each frozen SPORT:MARKET model remains PAPER/0u until >=50 authentic forward graded bets with positive mean no-vig CLV and positive ROI, independently verified. Never claim 100/100 readiness without evidence.

## Owner-reported audit inputs (unverified)
NFL headline 16-23 -3.68u; all-priced 44-44 -0.96u; live GB@DET 2-1 +0.75u; NBA team totals 4-6 -2.49u; DFS 94.92 actual versus 170.2 projected. Pending games remain ungraded.
