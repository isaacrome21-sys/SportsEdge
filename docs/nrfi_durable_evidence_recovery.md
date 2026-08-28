# NRFI/YRFI durable evidence recovery

This change hardens the cumulative NRFI/YRFI settlement lane without changing promotion thresholds or eligibility semantics.

Key properties:
- Rehydrates scored state from the durable `data` branch when ephemeral cache state is unavailable.
- Requires all three scored outputs before durable persistence begins.
- Stages `latest` completely before replacing the durable pointer directory.
- Preserves immutable per-run evidence and keeps the existing fail-closed verification contract.

This does not claim that GitHub Actions scheduling/runners are healthy, and it does not constitute V6 promotion evidence by itself.
