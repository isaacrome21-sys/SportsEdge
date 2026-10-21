from datetime import datetime, timedelta, timezone
from sportsedge.research.nba_early_season_prop_v2 import project_early_prop


def history(nowteam="A", current_games=1, future=False):
    r = []
    for season, count, team in [(2025, 12, nowteam), (2026, current_games, "A")]:
        for i in range(count):
            day = datetime(season, 1 if season==2025 else 10, 1,
                           tzinfo=timezone.utc) + timedelta(days=i)
            r.append({"player_id": "p1", "game_id": str(season)+"-"+str(i),
                      "season": season, "game_date": day.date().isoformat(),
                      "observed_at": (day + timedelta(hours=6)).isoformat(),
                      "source_ref": "gamelog", "position": "G",
                      "team_id": team, "minutes": 30,
                      "points": 20 if season==2025 else 32,
                      "rebounds": 6, "assists": 7})
    if future:
        r.append({"player_id":"p1","game_id":"after","season":2026,
                  "game_date":"2026-10-25","observed_at":"2026-10-25T22:00:00Z",
                  "source_ref":"gamelog","position":"G","team_id":"A",
                  "minutes":30,"points":150,"rebounds":30,"assists":30})
    return r


def read(rows, stat="points"):
    return project_early_prop(rows, player_id="p1", target_team_id="A",
        target_season=2026, target_date="2026-10-21",
        as_of="2026-10-21T17:00:00Z", stat=stat, line=22.5)


def test_v2_can_price_with_one_same_season_game_without_touching_v1():
    out = read(history())
    assert out["status"] == "RESEARCH_PROJECTION"
    assert out["current_season_prior_games"] == 1
    assert 20 < out["model_mean"] < 32
    assert abs(out["p_over"]+out["p_push"]+out["p_under"]-1) < 1e-12
    assert out["construction_relation"].startswith("NEW_V2")
    assert out["market_test"] == "NOT_RUN"


def test_pra_sums_same_game_stats_not_independent_marginals():
    out = read(history(), stat="pra")
    assert out["model_mean"] > 30
    assert out["p_over"] == 1


def test_future_result_produces_no_leak():
    orig = read(history())
    future = read(history(future=True))
    assert orig["model_mean"] == future["model_mean"]
    assert future["future_rows_excluded"] == 1


def test_current_season_reaches_v1_gate_and_v2_refuses():
    out = read(history(current_games=10))
    assert out["status"] == "REFUSED"
    assert out["reason"] == "NBA_EARLY_PROP_USE_FROZEN_CURRENT_SEASON_V1"


def test_transfer_is_explicit_unmodeled_watch():
    out = read(history(nowteam="B"))
    assert out["transfer_unmodeled"] is True
    assert out["status"] == "WATCH_TRANSFER_NOT_MODELED"


def test_missing_last_season_does_not_invent_prior():
    out = read(history()[10:])
    assert out["status"] == "REFUSED"
    assert out["reason"] == "NBA_EARLY_PROP_PRIOR_SEASON_HISTORY_INSUFFICIENT"
