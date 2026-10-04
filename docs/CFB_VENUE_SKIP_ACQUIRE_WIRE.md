# CFB venue skip acquire wire

Status: acquire calls `venue_indexes` and omits unresolved games. No placeholder coordinates.

Required behavior:
- Incomplete CFBD venue rows skip.
- Do not raise CFB_VENUE_COORDINATES_MISSING during venue index build.
- Do not raise CFB_GAME_VENUE_UNRESOLVED. Games whose venue cannot be resolved are omitted from the private games list and from reconstructed weather, and are recorded as `VENUE_UNRESOLVED_NO_PLACEHOLDER`.
- Unresolved games must not abort the 244-call acquisition.
- official_authority stays false.
