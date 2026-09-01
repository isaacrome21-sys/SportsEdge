from datetime import datetime, timezone
import json
import pytest

from sportsedge.sports.cfb.auto_slate import build_cfb_auto_context_slate, discover_cfb_auto_games
from sportsedge.sports.cfb.context_autopull import CFBContextError

PIT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.raw


def opener_for(payload):
    def opener(req, timeout=20):
        assert "classification=fbs" in req.full_url
        assert req.headers.get("Authorization") == "Bearer secret"
        return Response(payload)
    return opener


def game(game_id="10", start="2026-09-04T01:00:00Z", classification="fbs"):
    return {"id": game_id, "season": 2026, "week": 1, "startDate": start,
            "homeTeam": "Stanford", "awayTeam": "Miami", "neutralSite": False,
            "venue": "Stanford Stadium", "venueId": 1,
            "homeConference": "ACC", "awayConference": "ACC",
            "classification": classification}


def test_discovery_needs_no_game_list_and_filters_by_window():
    plan = discover_cfb_auto_games(as_of=PIT, cfbd_api_key="secret", horizon_minutes=7*24*60,
                                   opener=opener_for([game(), game("old", "2026-08-20T01:00:00Z")]))
    assert [row["game_id"] for row in plan["games"]] == ["10"]
    assert plan["subdivision"] == "FBS"


def test_auto_slate_materializes_core_metadata_and_explicit_missing():
    slate = build_cfb_auto_context_slate(as_of=PIT, cfbd_api_key="secret",
                                         opener=opener_for([game()]))
    assert slate["game_count"] == 1
    bundle = slate["games"][0]
    assert bundle["observations"]["game_metadata"]["status"] == "AVAILABLE"
    assert bundle["observations"]["venue_weather"]["status"] == "AVAILABLE"
    assert bundle["observations"]["injury_availability"]["status"] == "MISSING_PROVIDER"
    assert slate["model_p_eligible"] is False
    assert slate["truth_gate_eligible"] is False


def test_non_fbs_fixture_is_blocked_even_if_provider_misbehaves():
    with pytest.raises(CFBContextError, match="NON_FBS_GAME_BLOCKED"):
        discover_cfb_auto_games(as_of=PIT, cfbd_api_key="secret",
                                opener=opener_for([game(classification="fcs")]))
