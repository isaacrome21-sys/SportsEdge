"""No-vig exact team/first-half/F5 research, fake means only for pure math tests."""
from datetime import datetime,timezone
from unittest.mock import patch
import sportsedge.team_half_pricing as derivative

NOW=datetime(2026,10,11,20,30,tzinfo=timezone.utc)
KICKOFF="2026-10-12T00:00:00Z"
MOCK=(24.,20.,13.5,13.7,datetime(2026,10,12,tzinfo=timezone.utc),
      ["HOME_HISTORY_COUNT:5","AWAY_HISTORY_COUNT:5",
       "HOME_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS",
       "AWAY_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS",
       "WEATHER:INDOOR_VERIFIED"],"401999001")


def row(market="TEAM_TOTAL",team="HOME",side="OVER",line=22.5,odds=-110,sport="NFL",**extra):
    return {"sport":sport,"away":"Buffalo Bills","home":"Los Angeles Rams",
            "kickoff":KICKOFF,"team":team,"side":side,
            "market":market,"line":line,"odds":odds,"book":"draftkings",
            "quote_captured_at":"2026-10-11T20:29:00Z",**extra}


def priced(rows,raw=MOCK):
    with patch.object(derivative,"_scoring",return_value=raw):
        return derivative.price_team_half_rows(rows,now=NOW)[0]


def test_full_team_total_exact_opposite_market_and_team_identity():
    qs=[row(team="HOME",side="OVER"),row(team="HOME",side="UNDER"),
        row(team="AWAY",side="OVER"),row(team="AWAY",side="UNDER")]
    out=priced(qs)
    assert len(out)==4
    assert all(x["status"]!="NO_MODEL_OR_MARKET" for x in out)
    assert all(x["source"]=="FREE_ESPN_SCORE_DERIVATIVE_UNVALIDATED" for x in out)
    assert all(x["dk_no_vig_p"]==.5 for x in out)
    assert out[0]["team"]==out[1]["team"]=="HOME"
    assert out[2]["team"]==out[3]["team"]=="AWAY"
    assert out[0]["model_probability"]!=out[2]["model_probability"]
    assert all(x["model_source"].startswith("FREE_ESPN_SCORE_DERIVATIVE") for x in out)
    assert all(x["official_authority"] is False for x in out)


def test_unpaired_or_mixed_team_total_quote_never_creates_no_vig():
    missing=priced([row(team="HOME",side="OVER"),
                    row(team="AWAY",side="UNDER")])
    assert all(x["status"]=="NO_MODEL_OR_MARKET" for x in missing)
    assert all("EXACT_PAIRED_DK_QUOTE_REQUIRED" in x["reason"] for x in missing)


def test_first_half_totals_stay_unfitted_watch_even_if_edge_exists():
    qs=[row(market="TOTAL_1H",team="",line=17.5,side="OVER"),
        row(market="TOTAL_1H",team="",line=17.5,side="UNDER")]
    out=priced(qs)
    assert out[0]["score_period_fraction"]==.5
    assert out[0]["status"]=="WATCH_UNFITTED_PERIOD_SPLIT"
    assert out[0]["model_probability"]>0.5


def test_half_spread_requires_signed_opposite_threshold():
    qs=[row(market="SPREAD_1H",side="HOME",team="",line=-3),
        row(market="SPREAD_1H",side="AWAY",team="",line=3)]
    out=priced(qs)
    assert all(x["status"]!="NO_MODEL_OR_MARKET" for x in out)
    assert out[0]["score_period_fraction"]==.5
    unmatched=priced([qs[0],dict(qs[1],line=2.5)])
    assert all(x["status"]=="NO_MODEL_OR_MARKET" for x in unmatched)


def test_half_spread_signed_opposite_mirrors_at_integer_and_half_point_lines():
    # The favorite's -X and the underdog's +X are ONE market from opposite
    # sides: both rows must price off the same paired quotes, and the model
    # masses must be exact complements with the push counted exactly once.
    for fav_line, push_expected in ((-3, True), (-3.5, False), (-7, True)):
        qs=[row(market="SPREAD_1H",side="HOME",team="",line=fav_line),
            row(market="SPREAD_1H",side="AWAY",team="",line=-fav_line)]
        out=priced(qs)
        assert all(x["status"]!="NO_MODEL_OR_MARKET" for x in out)
        assert all(x["dk_no_vig_p"]==.5 for x in out)
        home,away=out[0],out[1]
        assert home["selection"]=="HOME" and away["selection"]=="AWAY"
        assert home["model_push_p"]==away["model_push_p"]
        total=home["model_probability"]+away["model_probability"]+home["model_push_p"]
        assert abs(total-1.0)<2e-6
        if push_expected:
            assert home["model_push_p"]>0
        else:
            assert home["model_push_p"]==0


def test_half_spread_same_sign_lines_never_pair():
    # HOME -3 with AWAY -3 is not the signed-opposite market; the unsigned
    # threshold must not be treated as a mirror image.
    qs=[row(market="SPREAD_1H",side="HOME",team="",line=-3),
        row(market="SPREAD_1H",side="AWAY",team="",line=-3)]
    out=priced(qs)
    assert all(x["status"]=="NO_MODEL_OR_MARKET" for x in out)
    assert all("EXACT_PAIRED_DK_QUOTE_REQUIRED" in x["reason"] for x in out)


def test_first_half_total_mismatched_thresholds_never_pair():
    # The spread signed-opposite rule must not leak into totals: OVER and
    # UNDER pair only at the identical threshold.
    qs=[row(market="TOTAL_1H",team="",line=17.5,side="OVER"),
        row(market="TOTAL_1H",team="",line=18.5,side="UNDER")]
    out=priced(qs)
    assert all(x["status"]=="NO_MODEL_OR_MARKET" for x in out)


def test_mlb_f5_ratio_five_ninths_and_stale_quotes():
    qs=[row(sport="MLB",market="F5_TOTAL",team="",line=4.5,
            quote_captured_at="2026-10-11T19:00:00Z",side="OVER"),
        row(sport="MLB",market="F5_TOTAL",team="",line=4.5,
            quote_captured_at="2026-10-11T19:00:00Z",side="UNDER")]
    out=priced(qs)
    assert all(x["score_period_fraction"]==5/9 for x in out)
    assert all(x["status"]=="WATCH_QUOTE_NOT_CURRENT" for x in out)


def test_player_owned_screenshot_features_never_flow_to_scoring():
    qs=[row(context={"home_rating":1000},game_id="attacker",model_p=.999),
        row(side="UNDER",context={"home_rating":1000},game_id="attacker")]
    out=priced(qs)
    assert out[0]["game_id"]=="401999001"
    assert out[0]["raw_home_mean"]==24
    assert out[0]["raw_away_mean"]==20


def test_unverified_live_or_missing_game_context_fails_closed():
    actual=derivative.price_team_half_rows([
        row(kickoff="2026-10-11T19:00:00Z")
    ],now=NOW,getter=lambda url:None)[0]
    assert actual[0]["status"]=="NO_MODEL_OR_MARKET"
    assert "PREGAME_UNIQUE_KICKOFF_REQUIRED" in actual[0]["reason"]


def test_illinois_school_excluded_before_data_fetch():
    q=row(sport="CFB",home="Illinois Fighting Illini")
    out=derivative.price_team_half_rows([q],now=NOW,getter=lambda url:None)[0]
    assert "ILLINOIS_COLLEGE_EXCLUDED" in out[0]["reason"]


def test_football_first_half_not_applied_to_mlb():
    out=priced([row(sport="MLB",market="TOTAL_1H")])
    assert out[0]["status"]=="NO_MODEL_OR_MARKET"
    assert "FOOTBALL_FIRST_HALF_ONLY" in out[0]["reason"]
