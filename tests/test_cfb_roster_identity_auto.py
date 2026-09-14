import json
from datetime import datetime, timezone

from sportsedge.sports.cfb.auto_objective_sources import (
    _fetch_fbs_roster_snapshot,
    build_cfbd_provider_factory,
)

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


def roster_payload():
    return [
        {"id": "101", "firstName": "Home", "lastName": "QB", "team": "Stanford", "position": "QB", "jersey": 1},
        {"id": "102", "firstName": "Home", "lastName": "WR", "team": "Stanford", "position": "WR", "jersey": 2},
        {"id": "201", "firstName": "Away", "lastName": "QB", "team": "Miami", "position": "QB", "jersey": 3},
    ]


def opener(req, timeout=25):
    assert "/roster?" in req.full_url
    assert "year=2026" in req.full_url
    assert "classification=fbs" in req.full_url
    assert req.headers.get("Authorization") == "Bearer secret"
    return Response(roster_payload())


def test_fetch_fbs_roster_snapshot_hashes_exact_source_and_groups_team():
    teams, uri, digest = _fetch_fbs_roster_snapshot(season=2026, cfbd_api_key="secret", opener=opener)
    assert set(teams) == {"Stanford", "Miami"}
    assert len(digest) == 64
    assert "classification=fbs" in uri
    assert teams["Stanford"][0]["athlete_id"] == "101"


def test_roster_identity_never_claims_depth_chart_role_available():
    factory = build_cfbd_provider_factory(cfbd_api_key="secret", opener=opener)
    providers = factory({
        "season": 2026,
        "week": 1,
        "game_id": "10",
        "home_team": "Stanford",
        "away_team": "Miami",
        "venue": "Stanford Stadium",
        "venue_id": 1,
    }, PIT)
    row = providers["depth_chart_role"]("10", PIT)
    assert row["status"] == "PARTIAL_ROSTER_IDENTITY_ONLY"
    assert row["source_name"] == "CFBD_FBS_ROSTER_IDENTITY"
    assert row["payload"]["depth_chart_confirmed"] is False
    assert row["payload"]["role_order_confirmed"] is False
    assert row["payload"]["identity_namespace"] == "CFBD_ATHLETE_ID"
