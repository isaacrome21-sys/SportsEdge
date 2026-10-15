from sportsedge.mlb_starter_source_audit import audit_starter_sources

def test_missing_sources_block():
    result = audit_starter_sources([], game_id='g1', team_id=108, cutoff='2026-10-15T17:00:00Z', first_pitch='2026-10-15T18:00:00Z')
    assert result['status'] == 'MISSING'
    assert result['play_authorized'] is False
