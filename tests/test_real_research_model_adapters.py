"""Actual pitcher joint-model adapter + proven football path contract tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from sportsedge.research_model_adapters import (
    mlb_pitcher_to_bridge_rows, football_player_stat_to_bridge_rows,
)
from sportsedge.research_three_sport_bridge import price_three_sport_research

MODEL_TIME = "2026-10-11T20:29:30Z"
SOURCE_TIME = "2026-10-11T20:28:00Z"
KICKOFF = "2026-10-12T00:00:00Z"
AS_OF = "2026-10-11T20:30:00Z"

POOL = [
    {"strikeouts": n, "outs": 15 + i, "earned_runs": i % 3,
     "hits_allowed": 4+i%3, "walks_allowed": i%3}
    for i,n in enumerate((5, 8, 7, 6, 9, 4, 7))
]
DATES = [(datetime(2026,9,1,tzinfo=timezone.utc) +
          timedelta(days=5*i)).isoformat() for i in range(len(POOL))]


def pitcher(**kw):
    args = dict(game_id="g", player_id="skubal_2026_mlb_id",
                market="PITCHER_K", side="OVER", line=7.5,
                features={"history_pool": POOL}, prior_start_times_utc=DATES,
                source_as_of_utc=SOURCE_TIME, as_of_utc=MODEL_TIME,
                kickoff_utc=KICKOFF, starting_pitcher_verified=True,
                home_team="Milwaukee Brewers", away_team="Los Angeles Dodgers")
    args.update(kw)
    return mlb_pitcher_to_bridge_rows(**args)[0]


def quotes():
    base = {"sport":"MLB","game_id":"g","player_id":"skubal_2026_mlb_id",
            "market":"PITCHER_K","line":7.5,"book":"draftkings",
            "quote_captured_at":"2026-10-11T20:29:00Z"}
    return [dict(base,selection="OVER",odds=113),
            dict(base,selection="UNDER",odds=-144)]


def test_real_pitcher_engine_emits_model_p_and_bridge_prices_both_sides():
    over = pitcher()
    under = pitcher(side="UNDER")
    assert over["status"] == under["status"] == "PRICED_RESEARCH"
    assert over["market_blind"] is True
    assert over["model_source"].startswith("mlb_pitcher_joint:")
    assert 0 < over["estimate_p"] < 1
    assert abs(over["estimate_p"] + under["estimate_p"] - 1) < 1e-8
    assert over["model_input_hash"] == under["model_input_hash"]
    board = price_three_sport_research([over,under],quotes(),as_of=AS_OF)
    assert len(board["rows"])==2
    assert all(r["status"] in (
        "WATCH_BELOW_EV_FLOOR", "WATCH_PRICE_CAP",
        "RESEARCH_CANDIDATE_NOT_VALIDATED") for r in board["rows"])
    assert all(r["dk_no_vig_p"]>0 for r in board["rows"])
    assert all(r["official_authority"] is False for r in board["rows"])


def test_mlb_missing_history_is_blocked_not_poisson_prior():
    assert pitcher(features={})["status"]=="NO_MODEL_OR_MARKET"
    assert "FIVE_PRIOR_STARTS" in pitcher(features={})["reason"]


def test_mlb_missing_pit_provenance_blocked():
    assert "TIMESTAMP_EACH" in pitcher(prior_start_times_utc=[])["reason"]
    assert "NOT_STRICTLY_PRIOR" in pitcher(source_as_of_utc="2026-10-11T20:35:00Z")["reason"]
    assert "HISTORY_LEAK" in pitcher(prior_start_times_utc=[KICKOFF]+DATES[1:])["reason"]


def test_mlb_duplicate_past_games_block():
    val = pitcher(prior_start_times_utc=[DATES[0]]*len(DATES))
    assert val["status"]=="NO_MODEL_OR_MARKET"
    assert "HISTORY_LEAK_OR_DUPLICATE" in val["reason"]


def test_mlb_starter_unverified_blocked():
    r = pitcher(starting_pitcher_verified=False)
    assert r["status"]=="NO_MODEL_OR_MARKET"
    assert r["reason"]=="STARTER_UNVERIFIED"


def test_mlb_forward_only_and_live_pitcher_forbidden():
    assert "NOT_STRICTLY_PRIOR_PREGAME_SOURCE" in pitcher(
        kickoff_utc="2026-10-11T20:28:00Z")["reason"]


def football(sport="NFL",**kw):
    p = SimpleNamespace(base_path=SimpleNamespace(game_id="g"))
    data = dict(sport=sport,game_id="g",player_id="WR-007",
                stat="receiving_yards",line=62.5,side="OVER",paths=[p],
                source_as_of_utc=SOURCE_TIME,as_of_utc=MODEL_TIME,
                kickoff_utc=KICKOFF,home_team="Green Bay Packers",
                away_team="Chicago Bears",market_blind_simulation_verified=True)
    data.update(kw)
    return football_player_stat_to_bridge_rows(**data)[0]


def test_actual_football_function_is_used_not_mock_stat_prior():
    # A fake attributed path is rejected by the real simulator.
    r=football()
    assert r["status"]=="NO_MODEL_OR_MARKET"
    assert "ATTRIBUTED_FOOTBALL_PATH_REQUIRED" in r["reason"]


def test_simulator_model_output_joins_bridge_if_attribution_is_verified():
    with patch("sportsedge.research_model_adapters.derive_player_stat_market",
               return_value={"over":0.61, "under":0.39, "push":0.0}):
        r=football()
    assert r["status"]=="PRICED_RESEARCH"
    assert r["market"]=="PLAYER_RECEIVING_YARDS"
    assert r["estimate_p"]==.61
    base={"sport":"NFL","game_id":"g","market":"PLAYER_RECEIVING_YARDS",
          "player_id":"WR-007","line":62.5,"book":"draftkings",
          "quote_captured_at":"2026-10-11T20:29:00Z"}
    q=[dict(base,selection="OVER",odds=-110),dict(base,selection="UNDER",odds=-110)]
    card=price_three_sport_research([r],q,as_of=AS_OF)
    assert card["rows"][0]["status"]=="RESEARCH_CANDIDATE_NOT_VALIDATED"


def test_cfb_il_college_still_excluded_by_bridge():
    with patch("sportsedge.research_model_adapters.derive_player_stat_market",
               return_value={"over":0.61,"under":0.39,"push":0.0}):
        r=football(sport="CFB",home_team="Illinois Fighting Illini")
    assert r["status"]=="PRICED_RESEARCH"
    q_base={"sport":"CFB","game_id":"g","market":"PLAYER_RECEIVING_YARDS",
            "player_id":"WR-007","line":62.5,"book":"draftkings",
            "home_team":"Illinois Fighting Illini","away_team":"Chicago Bears",
            "quote_captured_at":"2026-10-11T20:29:00Z"}
    qs=[dict(q_base,selection="OVER",odds=-110),
        dict(q_base,selection="UNDER",odds=-110)]
    card=price_three_sport_research([r],qs,as_of=AS_OF)
    assert card["rows"][0]["status"]=="NO_MODEL_OR_MARKET"


def test_no_market_blind_provenance_or_real_simulation_paths_blocks():
    assert football(market_blind_simulation_verified=False)["status"]=="NO_MODEL_OR_MARKET"
    assert football(paths=[])["status"]=="NO_MODEL_OR_MARKET"
    assert football(source_as_of_utc="2026-10-11T20:38:00Z")["status"]=="NO_MODEL_OR_MARKET"


def test_game_identity_mismatch_blocked_before_readout():
    r=football(paths=[SimpleNamespace(base_path=SimpleNamespace(game_id="different"))])
    assert r["status"]=="NO_MODEL_OR_MARKET"
    assert "PATH_GAME_ID_MISMATCH" in r["reason"]
