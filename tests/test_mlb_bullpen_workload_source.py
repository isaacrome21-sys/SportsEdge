from __future__ import annotations

from datetime import datetime, timezone
import json

from sportsedge.mlb_bullpen_workload_source import acquire_bullpen_workload


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self._raw


def _game(pk, when, away_id, home_id, status="Final"):
    return {
        "gamePk": pk,
        "gameDate": when,
        "status": {"abstractGameState": status},
        "teams": {"away": {"team": {"id": away_id}}, "home": {"team": {"id": home_id}}},
    }


def _box(team_id, other_id, pitchers, relief_stats, *, team_side="away"):
    players = {}
    for pid, stats in relief_stats.items():
        players[f"ID{pid}"] = {"stats": {"pitching": stats}}
    target = {"team": {"id": team_id}, "pitchers": pitchers, "players": players}
    other = {"team": {"id": other_id}, "pitchers": [], "players": {}}
    return {"teams": {team_side: target, "home" if team_side == "away" else "away": other}}


def test_bullpen_uses_only_prior_completed_games_and_excludes_starter_and_target():
    live = {"gameData": {"teams": {"away": {"id": 10}, "home": {"id": 20}}}}
    away_schedule = {"dates": [{"games": [
        _game(999, "2026-09-29T23:00:00Z", 10, 20, status="Preview"),
        _game(900, "2026-09-28T20:00:00Z", 10, 30),
        _game(899, "2026-09-27T20:00:00Z", 40, 10),
    ]}]}
    home_schedule = {"dates": [{"games": [
        _game(999, "2026-09-29T23:00:00Z", 10, 20, status="Preview"),
        _game(901, "2026-09-28T10:00:00Z", 20, 50),
    ]}]}
    boxes = {
        900: _box(10, 30, [1000, 1001, 1002], {
            1001: {"pitchesThrown": 25, "outs": 3, "battersFaced": 4},
            1002: {"pitchesThrown": 15, "outs": 3, "battersFaced": 4},
        }),
        899: _box(10, 40, [1003, 1001, 1004], {
            1001: {"pitchesThrown": 20, "outs": 3, "battersFaced": 4},
            1004: {"pitchesThrown": 12, "outs": 2, "battersFaced": 3},
        }, team_side="home"),
        901: _box(20, 50, [2000, 2001], {
            2001: {"pitchesThrown": 22, "outs": 4, "battersFaced": 5},
        }),
    }
    requested = []
    def opener(url, timeout=15):
        requested.append(str(url))
        text = str(url)
        if "/api/v1/schedule?" in text:
            return _Response(away_schedule if "teamId=10" in text else home_schedule)
        pk = int(text.split("/game/", 1)[1].split("/", 1)[0])
        return _Response(boxes[pk])

    bundle = acquire_bullpen_workload(
        game_pk=999,
        as_of=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
        live_payload=live,
        opener=opener,
    )

    assert bundle["status"] == "AVAILABLE"
    assert bundle["model_p_eligible"] is False
    assert bundle["evidence_eligible"] is False
    assert bundle["target_game_excluded"] is True
    away = bundle["teams"]["away"]
    assert away["prior_games_used"] == 2
    assert away["bullpen_pitches_24h"] == 40
    assert away["bullpen_pitches_48h"] == 72
    assert away["back_to_back_reliever_ids"] == [1001]
    assert away["high_usage_48h_reliever_ids"] == [1001]
    # The starters (1000/1003) never appear in reliever workload.
    assert "1000" not in away["reliever_workload"]
    assert "1003" not in away["reliever_workload"]
    assert not any("/game/999/boxscore" in url for url in requested)
