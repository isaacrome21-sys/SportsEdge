# SportsEdge Football Gap Register — 2026-09-05

This register tracks remaining CFB/NFL gaps after adding external quantitative benchmarks, market context, environment/travel, officials/trends, and player/roster/matchup research layers.

## Highest-priority remaining gaps

1. **Validated player-impact translation** — versioned transforms from QB/OL/WR/DB/pass-rush availability and usage into SportsEdge margin/total deltas. Until validated, player data remains context-only.
2. **Special teams model** — kicker/punter quality, field-goal range/accuracy, return/coverage, touchbacks, blocked kicks, field-position value.
3. **Coaching/game-management model** — fourth-down aggressiveness, timeout use, tempo shifts, two-minute behavior, red-zone decisions, coordinator/system changes.
4. **Pace/possession/play-volume interaction** — neutral pace, seconds per snap, situation-adjusted tempo, drive length, expected possessions, opponent interaction.
5. **Explosive-play/finishing-drive layer** — explosive pass/run creation/prevention, havoc, stuff rate, line yards, field position, points per scoring opportunity.
6. **Opponent-adjusted trench model** — OL continuity/experience, pressure allowed/created, sack avoidance, run-block vs front, pass-protection vs rush, replacement-level adjustments.
7. **Coverage/receiver matchup model** — man/zone tendencies, shells, target distribution, separation, slot/boundary, TE/RB receiving mismatch.
8. **Injury uncertainty distribution** — probabilistic availability, snap limits, recurrence risk, replacement quality, game-time decision uncertainty.
9. **Travel/circadian interaction model** — distance, time zones, body-clock kickoff, altitude/elevation, short rest and climate transition as validated features.
10. **Officials impact model** — crew tendencies and style interaction; NFL first, CFB where reliable data exists.
11. **Market microstructure/timing model** — open/current/close path, key-number crossing, source weighting, stale-line detection, steam/reversal classification.
12. **Price-shopping/execution layer** — best available price, line-equivalent EV, vig-normalized comparison, max playable line/price, boost handling separate from base edge.
13. **Props/derivatives engine** — team totals, 1H/1Q, alt markets, player props, TD markets, covariance-aware SGP handling.
14. **Live betting state model** — drive state, field position, possession, timeout state, score/time leverage, live pace and injuries.
15. **Calibration/validation by market and regime** — untouched forward holdout, CLV, no-vig ROI, Brier/log loss, slope/intercept/ECE and sample gates.
16. **Data freshness/provenance enforcement** — source timestamp, observation timestamp, freshness SLA, confidence, stale-data blocking, audit trail.
17. **Consensus-correlation control** — detect shared underlying ratings/data so external models are not treated as independent corroboration.
18. **FCS/lower-information handling** — explicit downgrade/block rules for sparse roster/injury data, huge spreads and shallow markets.
19. **Garbage-time/blowout distribution** — favorite pullback, backup-QB usage, pace suppression, late defensive softness, large-spread cover distributions.
20. **Postgame attribution/learning loop** — grade frozen card only; classify result by model miss, price miss, injury/news miss, timing miss, variance or execution error without hindsight rewriting.

## Governance
None of these gaps may be bypassed by external model agreement, capper consensus, public splits, or editorial confidence. External sources remain NOT Model_P unless a versioned SportsEdge transform is explicitly validated and promoted.
