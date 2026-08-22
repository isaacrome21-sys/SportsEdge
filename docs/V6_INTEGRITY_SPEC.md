# V6 Integrity Specification

## Purpose
Preserve the timing and eligibility rules that prevent settlement-time hindsight from changing whether a pregame candidate was eligible.

## Core invariant
**Eligibility is pregame.**

Settlement supplies the outcome. Settlement does **not** change eligibility.

```text
pregame evidence + predeclared rules
            |
            v
     eligibility decision
            |
            +--------------------+
            |                    |
            v                    v
       ELIGIBLE              REJECTED
            |
            v
        settlement
            |
            v
          outcome

Settlement may attach the outcome to the already-made eligibility decision.
It may not revise the pregame eligibility decision using hindsight.
```

## Four clocks
The authoritative V6 integrity specification defines **four clocks**. Their exact names and boundaries are not present in the available summary and therefore are not invented here. They must be copied verbatim from the authoritative source before implementation.

The required design property is that each clock is explicit and that pregame eligibility is determined only from evidence valid under the applicable pregame clocks.

## Rejection codes
The authoritative specification defines **three rejection codes**. Their exact strings are not present in the available summary and therefore are not reconstructed here. Implementations must use the authoritative code names exactly.

## Adversarial integrity test
The integrity suite must include an adversarial test that verifies a settled outcome contributes **zero** to every pregame eligibility input. The full zero-contribution checklist from the authoritative specification must be copied verbatim before the test is considered complete.

At minimum, the test structure must prove this directionality:

```text
settlement/outcome ---> scoring/evaluation only
settlement/outcome -X-> eligibility inputs
settlement/outcome -X-> pregame clocks
settlement/outcome -X-> feature availability
settlement/outcome -X-> rejection-code resolution
```

## Non-negotiable interpretation
A candidate cannot become eligible because it won, cannot become ineligible because it lost, and cannot have a missing/stale pregame input reinterpreted after settlement. The outcome is an evaluation label only.

## Source fidelity note
This document intentionally does not invent the missing four clock names, three rejection-code strings, or the full zero-contribution checklist. Those must be copied from the authoritative source specification before production implementation or acceptance sign-off.
