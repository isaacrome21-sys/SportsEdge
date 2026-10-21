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
                      "tipoff": (day + timedelta(hours=20)).isoformat(),
                      "observed_at": (day + timedelta(hours=23)).isoformat(),
                      "source_ref": "gamelog", "position": "G",
                      "team_id": team, "minutes": 30,
                      "points": 20 if season==2025 else 32,
                      "rebounds": 6, "assists": 7})
    if future:
        r.append({"player_id":"p1","game_id":"after","season":2026,
                  "game_date":"2026-10-25","tipoff":"2026-10-25T20:00:00Z",
                  "observed_at":"2026-10-25T23:00:00Z",
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


def test_result_receipt_predating_tipoff_is_refused_not_a_prior():
    records = history()
    records[0]["observed_at"] = "2025-01-01T19:00:00Z"
    try:
        read(records)
    except ValueError as e:
        assert "RESULT_RECEIPT_NOT_AFTER_TIPOFF" in str(e)
    else:
        assert False, "unplayed result entered historical pool"


def test_history_missing_genuine_tipoff_is_refused():
    records = history()
    del records[0]["tipoff"]
    try:
        read(records)
    except ValueError as e:
        assert "HISTORY_TIPOFF_REQUIRED" in str(e)
    else:
        assert False, "calendar label alone is not a pregame event witness"


def test_utc_tipoff_date_must_match_chicago_local_game_date():
    records = history()
    # Jan 2 08:00 UTC is Jan 2 02:00 CST, not the Jan 1 game_date.
    records[0]["tipoff"] = "2025-01-02T08:00:00Z"
    records[0]["observed_at"] = "2025-01-02T10:00:00Z"
    try:
        read(records)
    except ValueError as e:
        assert "LOCAL_GAME_DATE_MISMATCH" in str(e)
    else:
        assert False, "wrong local date accepted as evidence"



def test_same_season_team_change_must_be_transfer_watch_not_clean_projection():
    records = history(nowteam="A", current_games=2)
    # Previous season was with target A, but the first current-season
    # game occurred on another club. Prior implementation saw no trade.
    current = [x for x in records if x["season"] == 2026]
    current[0]["team_id"] = "B"
    out = read(records)
    assert out["status"] == "WATCH_TRANSFER_NOT_MODELED"
    assert out["transfer_unmodeled"] is True
    assert out["previous_team_ids"] == ["A"]
    assert out["current_team_ids"] == ["A", "B"]
    assert out["play_authority"] is False


def test_same_season_stable_team_keeps_research_only_status():
    out = read(history(nowteam="A", current_games=2))
    assert out["current_team_ids"] == ["A"]
    assert out["status"] == "RESEARCH_PROJECTION"
    assert out["transfer_unmodeled"] is False
    assert out["research_only"] is True


def test_pra_rejects_negative_component_even_when_sum_is_positive():
    records=history()
    records[0]["points"]=-2
    records[0]["rebounds"]=50
    try:
        read(records,stat="pra")
    except ValueError as e:
        assert "NBA_EARLY_PROP_STATS_INVALID" in str(e)
    else:
        assert False, "negative player points must never disappear inside PRA"


def test_prop_rejects_boolean_stats_and_minutes():
    for name in ("points","minutes"):
        records=history()
        records[0][name]=True
        try:
            read(records,stat="points")
        except ValueError as e:
            assert "NBA_EARLY_PROP_STATS_INVALID" in str(e)
        else:
            assert False, "a boolean is not a box score component"
