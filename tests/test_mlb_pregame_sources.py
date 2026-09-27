from __future__ import annotations

from datetime import datetime, timezone
import json

from sportsedge.mlb_injury_scratch_source import acquire_injuries_and_scratches
from sportsedge.mlb_statcast_preview_source import acquire_statcast_preview
from sportsedge.statcast_daily_source import StatcastSnapshot


class _Response:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


def _roster_player(player_id: int, name: str) -> dict:
    return {
        "person": {"id": player_id, "fullName": name},
        "status": {"code": "A", "description": "Active"},
        "position": {"abbreviation": "OF"},
    }


def test_statcast_default_skips_html_and_keeps_probables_without_boxscore():
    snapshot = StatcastSnapshot(
        start_date="2026-08-23",
        end_date="2026-09-21",
        retrieved_at="2026-09-22T15:00:00+00:00",
        source="BASEBALL_SAVANT_STATCAST",
        batter_rows=(),
        pitcher_rows=(
            {"entity_id": "501", "pa": 100, "window_start": "2026-08-23", "window_end": "2026-09-21"},
            {"entity_id": "502", "pa": 100, "window_start": "2026-08-23", "window_end": "2026-09-21"},
        ),
        raw_pitch_rows=200,
    )
    live_payload = {
        "gameData": {
            "probablePitchers": {
                "away": {"id": 501},
                "home": {"id": 502},
            }
        }
    }

    result = acquire_statcast_preview(
        game_pk=999001,
        as_of=datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc),
        live_payload=live_payload,
        official_date="2026-09-22",
        snapshot=snapshot,
    )

    assert result["preview"]["status"] == "SKIPPED"
    assert result["matchup"]["requested_pitcher_ids"] == [501, 502]
    assert result["matchup"]["bound_pitcher_count"] == 2
    assert result["model_p_eligible"] is False


def test_scratch_source_does_not_treat_missing_baseline_as_clean():
    live_payload = {
        "gameData": {
            "teams": {
                "away": {"id": 10},
                "home": {"id": 20},
            }
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {"battingOrder": [101, 102, 103]},
                    "home": {"battingOrder": [201, 202, 203]},
                }
            }
        },
    }

    def opener(req, timeout=20):
        url = getattr(req, "full_url", str(req))
        if "/roster?" in url and "/teams/10/" in url:
            return _Response({"roster": [_roster_player(101, "Away One"), _roster_player(104, "Away Four")]})
        if "/roster?" in url and "/teams/20/" in url:
            return _Response({"roster": [_roster_player(201, "Home One")]})
        if "/transactions?" in url:
            return _Response({"transactions": []})
        raise AssertionError(f"unexpected URL: {url}")

    result = acquire_injuries_and_scratches(
        game_pk=999002,
        as_of=datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc),
        live_payload=live_payload,
        opener=opener,
    )

    assert result["explicit_scratches"] == []
    assert result["lineup_change_evidence"]["evaluable"] is False
    assert result["scratch_detection_status"] == "NOT_EVALUABLE"
    assert result["model_p_eligible"] is False


def test_scratch_source_detects_player_removed_from_posted_lineup():
    live_payload = {
        "gameData": {
            "teams": {
                "away": {"id": 10},
                "home": {"id": 20},
            }
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {"battingOrder": [101, 102, 103]},
                    "home": {"battingOrder": [201, 202, 203]},
                }
            }
        },
    }

    def opener(req, timeout=20):
        url = getattr(req, "full_url", str(req))
        if "/roster?" in url and "/teams/10/" in url:
            return _Response({"roster": [_roster_player(101, "Away One"), _roster_player(104, "Away Four")]})
        if "/roster?" in url and "/teams/20/" in url:
            return _Response({"roster": [_roster_player(201, "Home One")]})
        if "/transactions?" in url:
            return _Response({"transactions": []})
        raise AssertionError(f"unexpected URL: {url}")

    result = acquire_injuries_and_scratches(
        game_pk=999003,
        as_of=datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc),
        live_payload=live_payload,
        opener=opener,
        baseline_lineup_ids={
            "away": [101, 102, 103, 104],
            "home": [201, 202, 203],
        },
    )

    assert result["scratch_detection_status"] == "EVIDENCE_PRESENT"
    assert result["lineup_change_evidence"]["evaluable"] is True
    assert result["lineup_change_evidence"]["removed_players"] == [
        {
            "side": "away",
            "player_id": 104,
            "player_name": "Away Four",
            "evidence": "POSTED_LINEUP_REMOVAL",
        }
    ]
