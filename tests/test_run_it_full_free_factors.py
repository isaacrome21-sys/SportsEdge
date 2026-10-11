"""Offline tests for truthful full factor research coverage, not invented odds."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("full_factor_run_it",ROOT/"artifacts"/"run_it_full.py")
full=importlib.util.module_from_spec(spec)
spec.loader.exec_module(full)
NOW=datetime(2026,10,11,13,0,tzinfo=timezone.utc)
KICKOFF="2026-10-11T20:25:00Z"


def row(**extra):
    x={"sport":"NFL","away":"Detroit Lions","home":"Arizona Cardinals",
       "market":"TOTAL","side":"UNDER","line":54.5,"odds":-102,"kickoff":KICKOFF}
    x.update(extra)
    return x


def test_full_runner_keeps_research_edge_and_flag_unwired_factors():
    result=full.run_full({"lines":[row()]}, now=NOW,auto_context=False)
    assert result["authority"]["official"] is False
    assert result["factor_coverage"]["coverage_is_not_validation"] is True
    f=result["factor_coverage"]["by_input_index"][0]["factors"]
    assert set(f)==set(full.FIELDS)
    assert f["coaching"]["status"]=="NOT_WIRED"
    assert f["matchups"]["status"]=="NOT_WIRED"
    assert f["rest_travel"]["status"]=="NOT_WIRED"
    assert f["market_context"]["status"]=="HEURISTIC_NOT_VALIDATED"
    assert f["injuries"]["status"]=="MISSING_UNVERIFIED"


def test_unknown_injury_source_not_rebranded_injury_free():
    r=full.run_full({"lines":[row()]},now=NOW,auto_context=False)
    assert "unavailable" in r["factor_coverage"]["by_input_index"][0]["factors"]["injuries"]["detail"].lower()


def test_prop_models_fail_closed_but_leave_traceable_factor_audit():
    r=full.run_full({"lines":[row(market="PLAYER_PASS_YARDS")]},
                    now=NOW, auto_context=False)
    assert not r["edges"]
    assert r["summary"]["status_counts"]["BLOCKED_INVALID"]==1
    a=r["factor_coverage"]["by_input_index"][0]
    assert a["factors"]["player_props"]["status"]=="UNSUPPORTED_NO_PROP_MODEL"
    assert a["factors"]["market_context"]["status"]=="MISSING_UNVERIFIED"


def test_no_verified_fixture_rejects_and_audits_source_missing():
    r=full.run_full({"lines":[row()]},now=NOW,getter=lambda url: {})
    assert not r["edges"]
    assert r["summary"]["status_counts"]["BLOCKED_CONTEXT_UNVERIFIED"]==1
    f=r["factor_coverage"]["by_input_index"][0]["factors"]
    assert f["weather"]["status"]=="MISSING_UNVERIFIED"
    assert f["team_quality"]["status"]=="MISSING_UNVERIFIED"


def test_top_level_sport_and_two_rows_have_matching_audits():
    x=row()
    x.pop("sport")
    y=dict(x,market="SPREAD",side="HOME",line=5.5,odds=-112)
    r=full.run_full({"sport":"NFL","lines":[x,y]},now=NOW,auto_context=False)
    assert len(r["evaluated_rows"])==len(r["factor_coverage"]["by_input_index"])==2
    assert all(a["sport"]=="NFL" for a in r["factor_coverage"]["by_input_index"])


def test_espn_league_group_injury_fallback_is_not_misread():
    from artifacts import free_models as base
    urls = []
    def get(url):
        urls.append(url)
        if "/teams/2/injuries" in url:
            return {"team": {"id": "2"}}  # team endpoint returned unrecognized shape
        if url.endswith("/football/nfl/injuries"):
            return {"injuries": [
                {"team":{"id":"2"}, "injuries":[
                    {"athlete":{"fullName":"QB Example","position":{"abbreviation":"QB"}},"status":"Out"},
                    {"athlete":{"fullName":"RB Example","position":{"abbreviation":"RB"}},"status":"Doubtful"},
                    {"athlete":{"fullName":"TE Example"},"status":"Questionable"}
                ]},
                {"team":{"id":"1"}, "injuries":[]}
            ]}
        raise AssertionError("unexpected URL " + url)
    provider=base.PublicContext(NOW,getter=get)
    impact,status=provider.injury_points("NFL",{"id":"2"})
    assert impact==-1.65
    assert "REPORTED_2" in status
    assert len(urls)==2


def test_unrecognized_injury_feed_does_not_mean_zero_injuries():
    from artifacts import free_models as base
    provider=base.PublicContext(NOW,getter=lambda _: {})
    impact,status=provider.injury_points("NFL",{"id":"2"})
    assert impact==0
    assert status=="MISSING_OR_UNRECOGNIZED_SOURCE"


def test_open_meteo_qualifies_venue_by_state_and_rejects_wrong_city():
    from artifacts import free_models as base
    from urllib.parse import parse_qs, urlparse
    seen = []
    def get(url):
        seen.append(url)
        if "geocoding-api" in url:
            q=parse_qs(urlparse(url).query)
            assert q["name"]==["Phoenix, Arizona"]
            assert q["countryCode"]==["US"]
            return {"results":[
                {"name":"Phoenix","admin1":"Arizona","latitude":33.4,"longitude":-112.1}]}
        if "api.open-meteo.com" in url:
            return {"hourly":{"time":["2026-10-11T20:00"],
                    "wind_speed_10m":[19],"precipitation_probability":[10]}}
        raise AssertionError("unexpected URL " + url)
    provider=base.PublicContext(NOW,getter=get)
    impact,status=provider.weather("NFL",{"venue":{"indoor":False,"address":{
        "city":"Phoenix","state":"Arizona"}}},base.dt(KICKOFF))
    assert impact == -0.8
    assert status.startswith("HEURISTIC_FORECAST")
    assert len(seen)==2


def test_fixture_verified_rest_does_not_invent_pricing_effect():
    from artifacts import free_models as base
    def getter(url):
        if "scoreboard?" in url:
            return {"events":[{"id":"today","date":KICKOFF,
                "competitions":[{"venue":{"indoor":True},
                    "competitors":[
                        {"homeAway":"away","team":{"id":"1","displayName":"Detroit Lions"}},
                        {"homeAway":"home","team":{"id":"2","displayName":"Arizona Cardinals"}}
                    ]}]}]}
        if "/teams?limit=" in url:
            return {"sports":[{"leagues":[{"teams":[
                {"team":{"id":"1","displayName":"Detroit Lions"}},
                {"team":{"id":"2","displayName":"Arizona Cardinals"}}
            ]}]}]}
        if "/schedule?" in url:
            team_id="1" if "/teams/1/" in url else "2"
            enemy="2" if team_id=="1" else "1"
            return {"events":[{"date":"2026-10-04T20:25:00Z",
                "status":{"type":{"completed":True}},
                "competitions":[{"competitors":[
                    {"team":{"id":team_id},"score":"24"},
                    {"team":{"id":enemy},"score":"18"}
                ]}]}]}
        if "/injuries" in url:
            return {"injuries":[]}
        raise AssertionError(url)
    result=full.run_full({"lines":[row()]},now=NOW,getter=getter)
    assert result["summary"]["rows"]==1
    a=result["factor_coverage"]["by_input_index"][0]["factors"]
    assert a["team_quality"]["status"]=="HEURISTIC_NOT_VALIDATED"
    assert a["rest_travel"]["status"]=="SCHEDULE_REST_OBSERVED_NO_PRICE_EFFECT"
    assert a["weather"]["status"]=="VERIFIED_INDOOR"
    assert a["injuries"]["status"]=="HEURISTIC_NOT_VALIDATED"
    assert all(abs(x["context"]["home_rating"])<10 for x in result["evaluated_rows"])


def test_manual_mode_not_promoted_to_observed_team_history():
    result=full.run_full({"lines":[row()]},now=NOW,auto_context=False)
    c=result["factor_coverage"]["by_input_index"][0]["factors"]
    assert c["team_quality"]["status"]=="MISSING_UNVERIFIED"
    assert c["recent_form"]["status"]=="MISSING_UNVERIFIED"


def test_phone_card_reports_unwired_factors_instead_of_calling_them_checked():
    from scripts.free_models_phone_issue import render_card
    card=full.run_full({"lines":[row()]}, now=NOW, auto_context=False)
    text=render_card(card,run_url="https://github.com/owner/repo/actions/runs/1")
    assert "Factor verification" in text
    assert "missing/not modeled" in text
    assert "Statcast, Next Gen" in text


def test_only_valid_game_lines_can_receive_model_edge_while_props_always_block():
    r=full.run_full({"lines":[row(),row(market="PASSING_YARDS",side="OVER",line=250.5)]},
                    now=NOW,auto_context=False)
    assert all(x["market"] in {"TOTAL", "SPREAD", "ML"} for x in r["edges"])
    assert r["evaluated_rows"][1]["status"]=="BLOCKED_INVALID"


def test_injury_schema_probe_logs_only_shape_when_unusable():
    from artifacts import free_models as base
    def getter(url):
        if "/teams/2/injuries" in url:
            return {}
        return {"injuries":[
            {"team":{"id":"55","displayName":"Not Target"}, "injuries":[
                {"athlete":{"fullName":"PRIVATE_TEST_NAME"},"status":"Out"}]}]}
    provider=base.PublicContext(NOW,getter=getter)
    impact,status=provider.injury_points("NFL",{"id":"2"})
    assert impact == 0.0
    assert status == "MISSING_OR_UNRECOGNIZED_SOURCE"
    bad=[r for r in provider.receipts if r["status"]=="UNUSABLE_SCHEMA"]
    assert len(bad)==1
    assert "TEAM[KEYS=" in bad[0]["reason"]
    assert "SAMPLE_TEAM_IDS=55" in bad[0]["reason"]
    assert "PRIVATE_TEST_NAME" not in str(bad)
    from scripts.free_models_phone_issue import render_card
    card=full.run_full({"lines":[row()]},now=NOW,auto_context=False)
    card["source_receipts"]=provider.receipts
    result=render_card(card)
    assert "1 unusable-schema reports" in result
    assert "team ID 2" in result
