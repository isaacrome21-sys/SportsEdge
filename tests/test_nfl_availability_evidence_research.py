from research.nfl_availability_evidence import assess

def test_unknown_never_active():
    r=assess([],game_id="g",player_id="p",cutoff="2026-10-15T18:00:00Z")
    assert r["status"]=="UNKNOWN" and not r["availability_binding_eligible"]

def test_x_only_unconfirmed():
    r=assess([dict(game_id="g",player_id="p",source_url="https://x.com/a/status/1",
        source_kind="X_UNVERIFIED",availability="ACTIVE",
        published_at="2026-10-15T16:00:00Z",observed_at="2026-10-15T16:01:00Z")],
        game_id="g",player_id="p",cutoff="2026-10-15T18:00:00Z")
    assert r["status"]=="UNCONFIRMED" and not r["play_authorized"]
