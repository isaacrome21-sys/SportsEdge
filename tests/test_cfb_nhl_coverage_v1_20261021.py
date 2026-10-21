from sportsedge.research.cfb_nhl_coverage_v1 import (
    nhl_research_snapshot, cfb_readiness,
)

T = "2026-10-21T17:00:00Z"
START = "2026-10-21T23:00:00Z"


def test_nhl_flyers_sabres_existing_engine_not_no_engine():
    v = nhl_research_snapshot(away="Philadelphia Flyers",
          home="Buffalo Sabres", event_id="nhl-1", event_start=START,
          as_of=T, fixture_source_ref="fixture-receipt")
    assert v["status"] == "RESEARCH_PROJECTION"
    assert v["book_quote_status"] == "NOT_READ_NO_DK_PRICES"
    assert abs(v["p_home_win"] + v["p_away_win"] - 1.0) < 1e-8
    assert abs(v["p_over"] + v["p_push"] + v["p_under"] - 1.0) < 1e-8
    assert v["play_authority"] is False


def test_nhl_florida_ottawa_maps():
    v = nhl_research_snapshot(away="Florida Panthers",
          home="Ottawa Senators", event_id="nhl-2", event_start=START,
          as_of=T, fixture_source_ref="fixture-receipt")
    assert v["status"] == "RESEARCH_PROJECTION"
    assert v["model_basis"].endswith("STATIC_SEASON_PRIORS")


def test_nhl_started_event_cannot_make_pregame_projection():
    v = nhl_research_snapshot(away="Flyers", home="Sabres",
          event_id="nhl-1", event_start=T, as_of=START,
          fixture_source_ref="fixture-receipt")
    assert v["status"] == "REFUSED"
    assert v["reason"] == "NHL_EVENT_ALREADY_STARTED"


def test_cfb_missing_manifest_and_quotes_is_specific():
    v = cfb_readiness(away="New Mexico State", home="Sam Houston",
          event_id="cfb-1", event_start=START, as_of=T)
    assert v["status"] == "EVIDENCE_INTAKE_MISSING"
    assert set(v["missing"]) == {
        "CFB_QB_FORM2_EXTERNAL_MANIFEST_PIN_MISSING",
        "CFB_PAIRED_DK_CAPTURE_MISSING"}
    assert v["play_authority"] is False


def test_cfb_operator_provided_evidence_is_not_authenticated_by_strings():
    v = cfb_readiness(away="New Mexico State", home="Sam Houston",
          event_id="cfb-1", event_start=START, as_of=T,
          qb_manifest_pin="asserted", paired_dk_capture_ref="asserted")
    assert v["status"] == "EVIDENCE_SUBMITTED_NOT_INDEPENDENTLY_VERIFIED"
    assert v["authority"] == "NONE"


def test_nhl_canonical_alias_self_matchup_refuses():
    import pytest
    for away, home in [
        ("Flyers", "Philadelphia Flyers"),
        ("PHI", "Philadelphia Flyers"),
        ("Sabres", "Buffalo Sabres"),
    ]:
        with pytest.raises(ValueError, match="NHL_FIXTURE_SAME_CANONICAL_TEAM"):
            nhl_research_snapshot(
                away=away, home=home, event_id="bad-self-matchup",
                event_start=START, as_of=T,
                fixture_source_ref="operator-supplied-only")
