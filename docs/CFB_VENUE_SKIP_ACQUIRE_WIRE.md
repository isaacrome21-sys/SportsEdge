# CFB venue skip acquire wire

Status: acquire script uses `sportsedge.sports.cfb.venue_coordinates` helpers.

Behavior:
- Incomplete CFBD venue rows are skipped (no CFB_VENUE_COORDINATES_MISSING abort).
- Games whose venue cannot be resolved are omitted from reconstructed weather.
- Payload games list is filtered to games with weather rows.
- official_authority stays false.
