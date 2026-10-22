"""Generic multi-sport PNG graphics cannot certify raw engine estimates."""

import pytest

from scripts.render_sportsedge_png import as_rows


@pytest.mark.parametrize("sport,market,row", [
    ("NFL", "total", {"selection": "UNDER", "estimate_p": 0.94,
                       "score_0_100": 99, "price_american": -110,
                       "edge_probability_points": 0.4, "ev_per_dollar": 0.3}),
    ("MLB", "TOTALS", {"selection": "UNDER", "estimate_p": 0.96,
                        "confidence_score": 100, "american_odds": -105,
                        "edge": 0.45, "ev_per_dollar": 0.35}),
    ("CFB", "SPREAD", {"selection": "HOME", "model_p": 0.97,
                        "score_0_100": 99, "american_odds": -110,
                        "edge": 0.45, "expected_roi": 0.35}),
])
def test_cross_sport_unverified_99_never_becomes_best_or_quality_score(sport, market, row):
    if sport == "NFL":
        payload = {"games": [{"home": "B", "away": "A",
                              "markets": [{"market": market, "pick": row}]}]}
    else:
        raw = {**row, "market": market, "matchup": "A @ B",
               "scored_status": "ACTIONABLE" if sport == "MLB" else None,
               "bet_status": "BET" if sport == "CFB" else None}
        payload = {"results": [raw]}
    rows = as_rows(payload, sport)
    assert len(rows) == 1
    assert rows[0]["status"] == "LEAN"
    assert rows[0]["score_value"] is None
    assert rows[0]["score_status"] == "WITHHELD_UNVALIDATED_PREDICTION_ACCURACY"
    assert rows[0]["raw_qualification_score"] in (99, 100)
    assert "RESEARCH_NOT_VALIDATED_FOR_PLAY" in rows[0]["reason"]
    # No silent inversion, odds fabrication or rewrite of underlying estimates.
    assert rows[0]["est"] == (row.get("estimate_p") or row.get("model_p"))
    assert rows[0]["price"] == (row.get("price_american") or row.get("american_odds"))


def test_untrusted_input_flags_cannot_self_approve():
    raw = {"market": "moneyline", "matchup": "A @ B", "status": "BET",
           "selection": "A", "score_0_100": 100,
           "price_american": -110, "estimate_p": 0.65,
           "ev_per_dollar": 0.2, "edge_probability_points": 0.1,
           "play_authority": True, "official_authority": True,
           "validated_vs_close": True, "score_authority": True,
           "model_validation": "VALIDATED_BEATS_MARKET"}
    rows = as_rows({"rows": [raw]}, "MLB")
    assert len(rows) == 1
    assert rows[0]["status"] == "LEAN"
    assert rows[0]["score_value"] is None
    assert raw["status"] == "BET"  # audited source unchanged
    assert raw["score_0_100"] == 100


def test_nfl_lean_and_missing_data_are_still_non_picks():
    payload = {"games": [{"home": "B", "away": "A", "markets": [{
        "market": "spread", "lean": {"selection": "B", "score_0_100": 99}}]}]}
    rows = as_rows(payload, "NFL")
    assert len(rows) == 1 and rows[0]["status"] == "LEAN"
    assert rows[0]["score_value"] is None
    assert "INCOMPLETE_DATA" in rows[0]["reason"]
