# MLB historical DraftKings replay audit — 2021–2025

Status: **FAIL for governed historical replay**

**NOT Model_P · NOT Truth Gate · NOT OFFICIAL**

## Frozen audit criteria

A historical source is eligible for SportsEdge replay only when it establishes all of the following without inference:

1. Per-quote timestamp provenance.
2. Same-book two-sided DraftKings pricing for the market being evaluated.
3. True closing-price provenance: the DraftKings quote used as close must be demonstrably the last admissible observation at or before first pitch.

Missing opposite-side prices, timestamps, or closes are never inferred.

## Candidate audited

Candidate public archive: `ArnavSaraogi/mlb-odds-scraper`, covering historical MLB sportsbook data including DraftKings.

## Audit result

| Requirement | Result | Reason |
| --- | --- | --- |
| Per-quote timestamp provenance | **FAIL** | The candidate does not establish a historical observation timestamp for each quote needed by the frozen replay contract. |
| Same-book two-sided DraftKings pricing | **PASS where represented** | Represented markets/rows can contain both DraftKings outcomes. This PASS applies only to rows where both sides are actually present; a missing side remains MISSING. |
| True closing-price provenance | **FAIL** | A `currentLine` value is not evidence that the quote was the final DraftKings observation at or before first pitch. The frozen contract forbids relabeling it as a close. |

## Decision

This candidate is **ineligible for governed historical replay**. Do not use it to calculate historical SportsEdge CLV, after-vig ROI, promotion evidence, or closing-price comparisons.

SportsEdge therefore defaults to **2027 prospective forward capture** unless another historical source independently passes all frozen replay-audit requirements.

The failed historical source may still be used for non-governed research where its actual fields support the analysis, but it must never be represented as PIT closing-line evidence.

## Queue update

`TODO → DONE — historical candidate audited; FAIL for governed replay because timestamp and true-close provenance are not established. 2027 defaults to forward capture unless another source passes.`
