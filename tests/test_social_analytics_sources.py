from sportsedge.social_analytics_sources import (
    MODEL_P_ELIGIBLE,
    SOURCES,
    TRUTH_GATE_ELIGIBLE,
    accounts_for_sport,
)


def test_social_analytics_sources_never_vote_in_model_or_truth_gate():
    assert MODEL_P_ELIGIBLE is False
    assert TRUTH_GATE_ELIGIBLE is False
    for sport in SOURCES:
        for row in accounts_for_sport(sport):
            assert row["source_role"] == "CONTEXT_ONLY"
            assert row["model_p_eligible"] is False
            assert row["truth_gate_eligible"] is False
            assert "model_p_vote" in row["prohibited_uses"]
            assert "confidence_boost_from_agreement" in row["prohibited_uses"]


def test_core_sports_have_primary_analytics_sources():
    expected = {
        "MLB": "@BallparkPal",
        "NFL": "@NextGenStats",
        "CFB": "@CFB_Data",
        "NBA": "@nbastats",
        "NHL": "@MoneyPuckdotcom",
        "PGA": "@DataGolf",
        "UFC": "@Fightnomics",
    }
    for sport, handle in expected.items():
        handles = {row["handle"] for row in accounts_for_sport(sport)}
        assert handle in handles


def test_accounts_for_sport_deduplicates_multi_sport_handles():
    rows = accounts_for_sport("MLB", include_multi=True)
    handles = [str(row["handle"]).lower() for row in rows]
    assert len(handles) == len(set(handles))
