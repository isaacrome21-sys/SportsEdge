# Binding value scanner V1

The scanner is defense-in-depth, not the primary binding mechanism.

Primary rule: sportsbook/event identity is stamped and preserved at quote acquisition/normalization, while model probability identity is produced by the model/readout. The orchestrator compares them. Missing identity blocks the individual priced row.

The recursive scanner rejects quote-origin fields if they appear inside a model-only payload. This helps catch nested/renamed plumbing mistakes but does not prove provenance by itself and must never be used to manufacture missing event/book/team/player identity.
