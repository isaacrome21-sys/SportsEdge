# MLB pitcher-K composite candidate v1

Status: **research only; not evaluation-ready; not deployed**.

This candidate is the next implementation step under
`config/research/mlb_card_postmortem_refinement_v1.json`. It binds three
components without choosing a new probability formula:

- the strictly-prior 5–10 start workload/leash bundle merged in #1729/#1731;
- the opponent-K context lane already validated in #1509 (beta = 1);
- the confirmed-lineup K context lane already validated in #1540 (W = 200,
  gamma = 0.5), with the existing opponent-K-only fallback when a lineup is
  unavailable.

The composite deliberately remains **not evaluation-ready**. The frozen
postmortem candidate also calls for pitcher whiff/chase and handedness. Those
inputs need their own immutable PIT-safe source contract before any untouched
outcomes are scored. This PR therefore creates no model probability, no weights,
no fit parameters, no card promotion, and no production call site.

The next allowed research step is to add auditable PIT-safe skill-source
receipts for whiff/chase and handedness, bind them to this candidate, freeze the
evaluation protocol, and only then evaluate on data that was not used to choose
the formula or thresholds.
