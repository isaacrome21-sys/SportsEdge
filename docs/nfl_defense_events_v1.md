# NFL defensive event v1 contract

This slice closes the declared player/team defensive stat plumbing without inventing independent prop draws.

- Engine A emits sacks as football plays with negative yards and no pass-attempt/completion state.
- Engine A emits interceptions/fumbles as turnover plays; Engine B only assigns defender identity afterward.
- Regulation and overtime defensive events are attributed independently and can be combined into one full-game ledger.
- Player sacks, player interceptions, tackles+assists, team sacks, and team turnovers are deterministic read-outs over those attributed paths.
- Tackle+assist markets remain fail-closed without an explicit settlement-provider binding.
- Defensive/return touchdowns are intentionally not claimed by this slice; they remain a separate score/possession-conservation implementation.
- No implementation in this slice changes NFL promotion status. Historical validation, successful external CI attestation, and forward CLV gates remain required before DEPLOYED.
