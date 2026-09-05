# Football Runtime Integration TODO

The personnel/context source registry and workflow are now defined, but this document makes the remaining implementation boundary explicit.

## Still required for true automatic ingestion
- authenticated/public adapters for PFF/SIS/SIC/CFBDepth/TWO-DEEP/NGS/etc. where terms/access allow
- normalized player/team identifiers across providers
- source timestamps and freshness SLAs
- conflict resolution when official and third-party data disagree
- cached snapshots for audit/replay
- per-source failure isolation and DATA_GAP emission
- runtime hooks that attach the normalized personnel context record to CFB/NFL RUN IT reports
- tests proving external context cannot mutate Model_P, Truth Gate, or promotion state

Until those adapters and runtime hooks exist, these sources are registered research inputs and must be collected via HYBRID/manual public-web research rather than claimed as fully automatic model ingestion.
