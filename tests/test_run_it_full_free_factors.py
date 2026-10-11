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
