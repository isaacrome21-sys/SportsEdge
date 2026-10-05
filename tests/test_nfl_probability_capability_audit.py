from scripts.audit_nfl_probability_capabilities import audit

def test_every_declared_nfl_market_is_accounted_for_without_granting_authority():
    report=audit()
    assert len(report["markets"]) == 51
    assert all(row["authority"]=="NONE_AUDIT_ONLY" for row in report["markets"])

def test_priority_markets_have_probability_readouts():
    by={row["market"]:row for row in audit()["markets"]}
    for market in ("spread","total","moneyline","anytime_td","two_plus_td","safety"):
        assert by[market]["probability_readout_present"] is True

def test_unimplemented_sequence_markets_stay_explicitly_missing():
    by={row["market"]:row for row in audit()["markets"]}
    for market in ("race_to_n_points","first_score","first_td"):
        assert by[market]["probability_readout_present"] is False
