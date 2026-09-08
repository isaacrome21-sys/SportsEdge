# Decisions

1. `threshold_domain` is explicit and required; no inference fallback.
2. Binding validator runs at orchestration after normalization and before engine execution.
3. Binding failures become per-row `BLOCKED` results.
4. Quote-origin identities are preserved from adapters; model layer cannot synthesize them.
5. Paired quotes independently validate and must share canonical event/team/book/threshold identity.
6. Unknown or ambiguous special-market semantics remain blocked.
