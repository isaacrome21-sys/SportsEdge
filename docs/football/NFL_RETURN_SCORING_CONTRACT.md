# NFL Return-Scoring Structural Contract

Status: **STRUCTURAL / UNFITTED / NOT PROMOTION EVIDENCE**

This contract records the source boundary for rare NFL return touchdowns.

## Ownership

- Engine A owns interception/fumble turnover events and defensive return touchdowns tied to those exact scrimmage plays.
- Engine C owns kickoff/punt return touchdowns because those scores arise from possession-transition events rather than offensive scrimmage opportunities.
- Engine C owns every post-touchdown try that is still legally required.
- The shared scoring path owns the final score timeline consumed by game/period/situational markets.

## Conservation rules

1. A defensive turnover-return TD is exactly six raw points and requires an `INTERCEPTION` or `FUMBLE` on the same play.
2. An interception return TD remains an incomplete pass for offensive passing statistics; the defensive score does not create a completion or passing yard.
3. A kickoff/punt return TD transition has `creates_next_drive=False`.
4. A scoring return is followed by its required try and then by a separate ensuing kickoff transition; only the ensuing kickoff may create the next offensive drive.
5. Every transition-sourced return TD has exactly one transition-sourced XP/2PT resolution when a try is required.
6. Overtime turnover-return TDs are represented as defensive scores on the turnover opportunity. Under the current regular-season Rule 16 state machine, possession obtained by the scoring defense satisfies the possession comparison and the return TD terminates the game at six without a post-game try.
7. OT kickoff/punt-return geometry is not claimed by this slice. Until the OT kickoff/return state machine is implemented, those rare components remain explicit validation blockers rather than synthetic market adjustments.

## Evidence discipline

The candidate return-TD rates in `NFLReturnScoringProfile` are structural placeholders only. They must be fitted from point-in-time historical return data before predictive validation and must not be promoted because this contract or its tests exist.
