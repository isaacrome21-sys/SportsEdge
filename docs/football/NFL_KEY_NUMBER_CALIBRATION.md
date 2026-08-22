# NFL key-number baseline and calibration

Status: research/design only. `INTEGRATION_UNRUN`.

## Baseline rule

Do **not** inject fixed probability mass at margins 3 or 7. The event-rich football simulator must generate the margin shape from football mechanics: touchdowns, field goals, extra points, two-point attempts, possessions, clock/game state, and end-game strategy.

A separate exact-point-mass `KeyNumberMarginModel` is legacy/misspecification-prone for the production target and must not be treated as the intended architecture.

## Validation target

Use a large simulated sample and compare the resulting signed and absolute margin PMFs against real NFL history. Margins of 3 and 7 should emerge near their historical frequencies within a tolerance declared **before** looking at the simulated result.

A miss is evidence of simulator misspecification. It must not be repaired at the market read-out by injecting 3/7 mass or adding spread-specific fudge factors.

## Historical anchor

The baseline historical window is the **last five completed NFL seasons**, with the exact season years frozen in the validation artifact at execution time. Do not use a timeless constant: scoring rules, kicking accuracy, overtime rules, and strategy change margin frequencies.

The history artifact should publish at minimum:

- `historical_seasons`
- `total_games`
- `absolute_margin_pmf`
- `signed_margin_pmf`
- source/provenance
- artifact hash

Do not copy `P(|margin|=3)` to both +3 and -3; signed frequencies are separate observations.

## Acceptance state

- PRESENT ON MAIN: no (this research-branch spec is not main)
- RUNTIME EXECUTED: no
- PRODUCING EVIDENCE: no

Execution waits for the event-rich football simulator. The current score-level simulator cannot satisfy this acceptance test by construction.
