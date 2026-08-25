# NFL Return-Scoring Structural Contract

Status: **STRUCTURAL / UNFITTED / NOT PROMOTION EVIDENCE**

This contract records the source boundary for rare NFL return touchdowns.

## Ownership

- Engine A owns interception/fumble turnover events and defensive return touchdowns tied to those exact scrimmage plays.
- Engine C owns kickoff/punt return touchdowns because those scores arise from possession-transition events rather than offensive scrimmage opportunities.
- Engine C owns every post-touchdown try that is still legally required.
- The shared scoring path owns the final score timeline consumed by game/period/situational markets.
- `NFLRegularSeasonCompleteOTSimulator` is the authoritative structural regular-season OT composition when period-5 kickoff/punt possession geometry is required; the older `NFLRegularSeasonOTSimulator` remains the lower-level scrimmage kernel.

## Conservation rules

1. A defensive turnover-return TD is exactly six raw points and requires an `INTERCEPTION` or `FUMBLE` on the same play.
2. An interception return TD remains an incomplete pass for offensive passing statistics; the defensive score does not create a completion or passing yard.
3. A kickoff/punt return TD transition has `creates_next_drive=False` in regulation; in overtime the period-5 transition owns the receiving club's Rule 16 opportunity and does not invent a scrimmage spot after a scoring return.
4. A scoring return is followed by its required try when the game state requires one; if play continues, a separate ensuing kickoff transition establishes the next possession.
5. Every transition-sourced return TD has exactly one transition-bound scoring identity and reconciles with the Rule 16 opportunity ledger.
6. Overtime turnover-return TDs are represented as defensive scores on the turnover opportunity. Under the current regular-season Rule 16 state machine, possession obtained by the scoring defense satisfies the possession comparison and the return TD terminates the game at six without a post-game try.
7. OT opening/score kickoffs, punt returns, missed-FG changes of possession, turnover spots and return touchdowns are composed through `NFLRegularSeasonCompleteOTSimulator`. Transition points plus scrimmage points must exactly equal every settled opportunity's points.

## Evidence discipline

The candidate return-TD and field-position rates are structural placeholders only. They must be fitted from point-in-time historical data before predictive validation and must not be promoted because this contract or its tests exist. External CI attestation and the forward CLV promotion gates remain independently required.
