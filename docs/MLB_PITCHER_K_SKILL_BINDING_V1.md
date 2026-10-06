# MLB pitcher-K Statcast skill binding v1

Status: **research only; source-complete after an eligible main capture; not evaluation-ready**.

This binding step connects the composite pitcher-K candidate to the additive
Statcast pitcher skill observations. It accepts a skill snapshot only when its
persisted provenance proves the collector ran from `refs/heads/main` and marks
that run eligible for forward evaluation.

The binding verifies whiff/chase rates against their raw counts, requires a
single observed L/R throwing hand, preserves the 30-day source window, and
stores the exact main head/run identity. Feature-branch captures are rejected.

After a valid binding, `missing_components` is empty and
`source_complete = true`, but `evaluation_ready` remains false. This step
still defines no probability formula, fit parameter, market threshold, card
promotion, or production call site. A separate preregistration must freeze the
formula and untouched evaluation protocol before any outcomes are scored.
