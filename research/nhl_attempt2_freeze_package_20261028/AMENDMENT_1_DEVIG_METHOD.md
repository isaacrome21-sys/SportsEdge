# NHL_ATTEMPT2_V1 — Amendment 1: Stage B de-vig method

**Status: DRAFT — FOR OWNER FREEZE ACT. This amendment authorizes
nothing, freezes nothing, pins nothing, and starts no clock.** It is
draft material prepared for adoption by a future owner freeze act of
this package. Until that act adopts it, it changes no term of the
package, and it is deliberately absent from `SPEC_HASHES.txt`: the
act that adopts it pins it.

## 1. What this amendment settles

The package's terms record (gap G-3) quotes Stage B's market leg as
"DK closing no-vig probabilities" without naming the de-vig method
that produces them. A method left unnamed at freeze time would have
to be chosen at the one look — **Feb 1, 2027** — which is criterion
invention at verdict time: the three de-vig families in this repo do
not agree on longshots, and the choice moves the market leg Stage B
is gated against. This amendment names the method **now, before any
Stage B clock starts** (Stage B window: Dec 1, 2026 – Jan 31, 2027):

> **Stage B de-vig method: POWER_V1, per the frozen platform policy
> `EDGE_FLOOR_DEVIG_V1`, executed by the platform implementation
> `sportsedge.devig.devig_with_policy`** — POWER_V1 as both the
> stable and the longshot candidate estimator; longshot trigger at
> either side >= +400; the three-method sensitivity spread computed
> on every longshot pair, with a spread over the policy's 1.0pp
> limit BLOCKing that pair's market probability (the pair carries no
> market leg rather than a probability from a softer method);
> haircut 0, so the market probability is the pure POWER_V1 fair
> probability.

## 2. Authority

Owner ruling, Oct 29, 2026: the conformance audit (gap A2) found
three de-vig regimes coexisting — the frozen platform policy selects
POWER_V1 while family evaluators hand-roll proportional de-vig
(`q1/(q1+q2)`), the softest-on-dogs baseline. Isaac delegated the
fix ("Just do what you would suggest"); the ruling — forward
evaluators use the frozen POWER_V1 policy — was issued on relay
#2447 (comment 6513411240) and applied the same day to the Lane A
card gates. This amendment brings this package under the same
program-wide rule. Proportional de-vig is **not** an admissible
substitute for the Stage B market leg, at the look or anywhere else.

## 3. What this amendment does not touch

- **Stage A terms are untouched** — every Stage A term, gate, and
  date in the package stands exactly as written; the Stage A
  verdict (Nov 30, 2026) still gates Stage B.
- The Stage B window, the one-look rule, the verdict gates, and the
  paired game-cluster bootstrap terms are unchanged. This amendment
  names the de-vig method only; it does not settle gap G-3's
  close-validity terms (staleness bound, missing/one-sided/late
  FINAL writes, insufficient-close share), which remain for their
  own completion proposal.
- Nothing here is a freeze act. The package's two standing gates
  (Stage A verdict; owner freeze act) are unaffected, and no clock
  of any kind starts by this document's existence or merger.

## 4. Adoption

Adoption is an owner act, recorded with the freeze act: on adoption
this file's hash joins `SPEC_HASHES.txt` and the terms record's
Stage B market-leg wording reads "DK closing no-vig probabilities
(POWER_V1 per Amendment 1)". If the act declines the amendment, the
method question returns to the owner — it may not be answered at
the Feb 1, 2027 look.
