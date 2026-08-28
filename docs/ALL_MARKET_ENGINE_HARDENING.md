# All-market engine hardening invariants

This pass improves shared betting-engine safety without claiming that every predictive model has earned better holdout performance.

## Shared invariants

1. Any market reaching the canonical Truth Gate has bankroll-safe Kelly sizing. The default remains quarter-Kelly behavior, but misconfiguration cannot recommend more than 100% of bankroll and callers may impose a lower cap.
2. Kelly controls reject boolean/non-finite values instead of accepting Python's bool-as-int coercion.
3. Two-way devig requires an unambiguous quote identity. `is_alternate` must be a real boolean; string/integer lookalikes fail closed so main and alternate markets cannot be silently paired through coercion.
4. Existing frozen edge floors, freshness requirements, deployment binding, push semantics, and promotion evidence remain unchanged.
5. No code merge is itself validation or promotion evidence. Sport/market-specific predictive changes still require point-in-time holdout/forward evidence under their existing contracts.

## Follow-on engine work

Sport-specific engines that bypass the canonical Truth Gate or maintain independent pricing helpers should migrate to these invariants before promotion. Semantic aliases must also fail closed when two sportsbook market names are not mathematically identical for every supported line.
