# CFB venue skip acquire wire

Status: helpers are on main from #848. Acquire now calls them and skips unusable venues.

Required behavior:
- Incomplete CFBD venue rows skip.
- Do not raise CFB_VENUE_COORDINATES_MISSING during venue index build.
- Games whose venue cannot be resolved are omitted from reconstructed weather, not used to abort the 244-call acquisition.
- official_authority stays false.
