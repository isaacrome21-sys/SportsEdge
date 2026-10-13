"""Research-only MLB / CFB / NFL game and player-prop paired-DK quote bridge."""
from sportsedge.research_three_sport_bridge import price_three_sport_research

ASOF = "2026-10-11T20:30:00Z"
FUTURE = "2026-10-12T03:00:00Z"


def model(sport="MLB", market="PITCHER_K", line=5.5, player="123",
          selection="OVER", **other):
    row = {"sport": sport, "game_id": "test-game", "market": market,
           "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
           "player_id": player, "line": line, "selection": selection,
           "estimate_p": .61, "push_p": 0,
           "status": "PRICED_RESEARCH", "model_source": "TEST_INDEPENDENT_SOURCE",
           "market_blind": True, "as_of_utc": "2026-10-11T20:29:00Z",
           "kickoff_utc": FUTURE}
    row.update(other)
    return row


def quote(sport="MLB", market="PITCHER_K", line=5.5, player="123",
          selection="OVER", odds=-110, captured="2026-10-11T20:29:30Z", **other):
    row = {"sport": sport, "game_id": "test-game", "market": market,
           "home_team": "Minnesota Golden Gophers", "away_team": "Michigan Wolverines",
           "player_id": player, "line": line, "selection": selection,
           "odds": odds, "book": "draftkings", "quote_captured_at": captured}
    row.update(other)
    return row


def run(m=None, o=None, u=None):
    return price_three_sport_research(
        [m if m is not None else model()],
        [o if o is not None else quote(),
         u if u is not None else quote(selection="UNDER")], as_of=ASOF)["rows"][0]


def test_mlb_pitcher_k_prop_has_real_probability_and_price_math():
    row = run()
    assert row["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"
    assert row["model_probability"] == .61
    assert row["dk_no_vig_p"] == .5
    assert row["edge_pp"] == 11
    assert row["ev_per_dollar"] > 0 and row["official_authority"] is False


def test_cfb_and_nfl_player_props_use_same_quote_bridge():
    for sport, market in (("CFB", "PASSING_YARDS"), ("NFL", "RECEIVING_YARDS")):
        row = run(model(sport=sport, market=market),
                  quote(sport=sport, market=market),
                  quote(sport=sport, market=market, selection="UNDER"))
        assert row["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"


def test_games_across_three_sports_preserve_spread_signs():
    for sport in ("CFB", "NFL", "MLB"):
        row = run(model(sport=sport, market="SPREAD", line=-3, player="", selection="HOME"),
                  quote(sport=sport, market="SPREAD", line=-3, player="", selection="HOME"),
                  quote(sport=sport, market="SPREAD", line=3, player="", selection="AWAY"))
        assert row["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"


def test_invalid_prop_identity_never_leaks_another_players_probability():
    row = run(model(), quote(player="wrong"),
              quote(selection="UNDER", player="wrong"))
    assert row["status"] == "NO_MODEL_OR_MARKET"


def test_mismatched_prop_threshold_does_not_make_up_no_vig():
    row = run(u=quote(selection="UNDER", line=6.5))
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"


def test_unverified_odd_capture_does_not_become_playable_research_candidate():
    row = run(o=quote(captured=None), u=quote(selection="UNDER", captured=None))
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "PAIRED_QUOTES_CAPTURE_TIMESTAMPS_REQUIRED"
    assert "dk_no_vig_p" not in row
    old = "2026-10-11T19:00:00Z"
    row2 = run(o=quote(captured=old), u=quote(selection="UNDER", captured=old))
    assert row2["status"] == "WATCH_QUOTE_NOT_CURRENT"


def test_opposite_quote_timestamps_within_two_minutes_pair():
    row = run(o=quote(), u=quote(selection="UNDER",
                                 captured="2026-10-11T20:29:20Z"))
    assert row["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"
    assert row["paired_quote_skew_seconds"] == 10.0
    assert len(row["paired_quote_captured_at"]) == 2


def test_odds_beyond_max_straight_price_are_watch_only():
    row = run(o=quote(odds=-170), u=quote(selection="UNDER", odds=150))
    assert row["status"] == "WATCH_PRICE_CAP"


def test_started_game_never_recycles_pregame_projection():
    row = run(m=model(kickoff_utc="2026-10-11T19:00:00Z"))
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert "GAME_STARTED" in row["reason"]


def test_live_requires_explicit_live_model_clock_scores_and_live_prices():
    row = run(m=model(kickoff_utc="2026-10-11T19:00:00Z", phase="LIVE",
                      live_model=True, live_state={
                          "period": 3, "clock": "11:40",
                          "home_score": 17, "away_score": 10,
                          "verified_source": "ESPN"}))
    assert row["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"
    missing = run(m=model(kickoff_utc="2026-10-11T19:00:00Z",
                          phase="LIVE", live_model=True))
    assert missing["status"] == "NO_MODEL_OR_MARKET"
    assert "VERIFIED_LIVE_MODEL" in missing["reason"]


def test_push_probability_uses_conditional_fair_price_but_correct_ev():
    row = run(
        m=model(market="PITCHER_OUTS", line=18, estimate_p=.54, push_p=.08),
        o=quote(market="PITCHER_OUTS", line=18),
        u=quote(market="PITCHER_OUTS", line=18, selection="UNDER"))
    assert abs(row["model_conditional_p"] - .54 / .92) < 1e-6
    assert abs(row["ev_per_dollar"] - (.54 * 100/110 - .38)) < 1e-5


def test_non_model_probability_and_market_contamination_fail_closed():
    assert run(m=model(market_blind=False))["status"] == "NO_MODEL_OR_MARKET"
    assert run(m=model(status="NO_MODEL", estimate_p=None))["status"] == "NO_MODEL_OR_MARKET"


def test_unrelated_books_do_not_create_draftkings_pair():
    row = run(u=quote(selection="UNDER", book="fanduel"))
    assert row["status"] == "NO_MODEL_OR_MARKET"


def test_illinois_college_is_blocked_for_game_and_player_props():
    for market, player in (("PASSING_YARDS","qb-123"), ("SPREAD","")):
        m = model(sport="CFB",market=market,player=player,away_team="Illinois Fighting Illini")
        q1 = quote(sport="CFB",market=market,player=player,away_team="Illinois Fighting Illini")
        q2 = quote(sport="CFB",market=market,player=player,away_team="Illinois Fighting Illini",
                   selection="UNDER" if player else "AWAY")
        result = run(m=m,o=q1,u=q2)
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert "ILLINOIS_COLLEGE_EXCLUDED" in result["reason"]


def test_f5_moneyline_does_not_require_threshold():
    m = model(sport="MLB",market="F5_ML",player="",line=None,selection="HOME")
    q1 = quote(sport="MLB",market="F5_ML",player="",line=None,selection="HOME")
    q2 = quote(sport="MLB",market="F5_ML",player="",line=None,selection="AWAY")
    assert run(m=m,o=q1,u=q2)["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"
