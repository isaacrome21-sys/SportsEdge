# NFL touchdown and prop readouts

This change completes deterministic **research readouts**, not fitted engines or
promotion. It does not change frozen model code, attempt ledgers, runtime engine
availability, Truth Gate thresholds, or OFFICIAL authority.

`touchdown_readouts.py` consumes complete scoring paths with an explicit source
event order, participant identities, and an exact scorer binding for every TD.
It supports anytime, 2+, 3+, first/last scorer, exact count distributions, TD
over/under/push, team/game TD counts, and sides/totals from the same score sample.
Passing TDs do not credit the passer. No-TD games stay in the denominator. Return,
defensive and overtime TDs require identities; missing identity blocks the readout.
Tied clocks use explicit source order, never lexical event-ID order. Separate XP
and two-point events are required. Duplicate simulations, mixed games, unknown
scoring events, invalid points and unknown players fail closed.

`prop_readout_batch.py` routes 18 offensive statistics, four kicker statistics,
four defensive player statistics, two team defensive statistics, and six TD
markets. It retains each request and its blocker. All results are research-only;
it never labels these probabilities Model_P or creates staking permission.
Target and tackle markets retain the existing settlement-provider requirements.
Engine path sets are not treated as a joint parlay sample.

The complete-scorer API is an input contract, not proof that the live simulator
or provider can populate it. Complete source-bound returner/defender/OT identity
adapters, pregame inactive-status timestamps and sportsbook void/participation
rules still need integration before bettor-facing TD settlement. A caller cannot
turn a truncated path into evidence merely by declaring full-game scope.

Remaining predictive work: fit and freeze G1 candidates under the existing
attempt budget, run admitted chronological evaluations with shared-component
evidence, obtain independent prospective calibration/certification and promote
each exact model/market identity. Integer game spreads/totals in frozen attempt-9
remain blocked; research path push probabilities do not validate that model.

Verification: focused tests cover touchdown ordering/identity, no-TD outcomes,
count push mass, same-sample game totals, prop routing and generator reuse, plus
existing player, period, kicker and defensive readouts. No historical candidate
evaluation was run and no attempt was consumed.

## Receptions validation integrity

The G1 chronological readout now rejects duplicate player/season/week identities
(including whitespace aliases), missing or invalid reception counts, invalid
chronology and invalid history/line configuration before fitting. Missing data
cannot become a zero reception outcome, and duplicate rows cannot leak the
current outcome into prior history. Metric helpers reject nonfinite quantities,
nonbinary labels and probabilities outside [0, 1] before numerical clipping.
Tests cover reversed inputs, season rollover, separate player histories, future
outcome isolation and invalid data in both training and evaluation rows. These
are fixture checks, not a historical validation attempt or promotion evidence.

Hosted verification of the original TD/prop commit: the focused contract passed;
both full-suite jobs recorded 3,177 passed and one failure in the existing freeze
reconciliation boundary assertion against main 78aae277. That repository release
block remains unresolved; no test, governance hash or release gate was bypassed.
