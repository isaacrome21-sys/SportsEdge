# NFL integrated regulation halftime transition fix

## Confirmed failure

The integrated regulation simulator can reach `remaining == 1800`, create the explicit halftime kickoff, and then immediately stop the newly created third-quarter drive because the drive loop also interprets `remaining == 1800` as an unconditional pre-halftime boundary. The pending halftime kickoff is then cleared, and the next outer iteration raises `INTEGRATED_NEXT_POSSESSION_TRANSITION_REQUIRED`.

## Fix

Treat `remaining == 1800` as a stop/clear boundary only while `halftime_kicked` is false. Once the halftime kickoff has been created, the same game-clock value represents the start of Q3 and the receiving offense must be allowed to run a play.

## Required verification

Run `tests/test_football_nfl_integrated_regulation.py` in full. The fix is not considered composition-verified until the dedicated suite completes without the possession-transition error and reconciliation assertions pass.

This PR intentionally does not modify scoring probabilities, drive profiles, special-teams probabilities, field-position geometry, market inputs, CLV logic, or promotion gates.
