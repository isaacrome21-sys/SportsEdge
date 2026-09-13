from sportsedge.mlb_validation_dashboard import build_dashboard_row


def _base(**kw):
    row = {"gate_decision": "PASS", "outcome": "LOSS", "clv": -.02,
           "confidence_tier": "ELITE", "brier": .20, "uncertainty_haircut_magnitude": .01}
    row.update(kw)
    return row


def test_dashboard_keeps_predictive_and_infrastructure_status_separate():
    d = build_dashboard_row(market="NRFI", rows=[_base()], predictive_status="RESEARCH",
        infrastructure_status="STALE", model_sha="m", feature_sha="f",
        last_durable_evidence_timestamp="2026-08-17T16:07:54Z", uncertainty_enabled=True)
    assert d.predictive_status == "RESEARCH"
    assert d.infrastructure_status == "STALE"


def test_gate_score_null_below_300():
    d = build_dashboard_row(market="HR", rows=[_base()] * 20, predictive_status="RESEARCH",
        infrastructure_status="HEALTHY", model_sha="m", feature_sha="f",
        last_durable_evidence_timestamp=None, uncertainty_enabled=True)
    assert d.gate_quality_score is None


def test_monotonicity_insufficient_when_required_tier_short():
    rows = [_base(gate_decision="BET", confidence_tier="ELITE", clv=.02, brier=.18)] * 150
    d = build_dashboard_row(market="ML", rows=rows, predictive_status="RESEARCH",
        infrastructure_status="HEALTHY", model_sha="m", feature_sha="f",
        last_durable_evidence_timestamp=None, uncertainty_enabled=False)
    assert d.tier_monotonicity_status == "INSUFFICIENT"
    assert d.tier_monotonicity_score is None


def test_missing_closing_price_does_not_pollute_clv():
    rows = [_base(gate_decision="BET", clv=None), _base(gate_decision="PASS", clv=-.03)]
    d = build_dashboard_row(market="TOTAL", rows=rows, predictive_status="RESEARCH",
        infrastructure_status="HEALTHY", model_sha="m", feature_sha="f",
        last_durable_evidence_timestamp=None, uncertainty_enabled=True)
    assert d.accepted_mean_clv is None
    assert d.rejected_mean_clv == -.03


def test_uncertainty_haircut_summary():
    rows = [_base(uncertainty_haircut_magnitude=.02), _base(uncertainty_haircut_magnitude=0)]
    d = build_dashboard_row(market="K", rows=rows, predictive_status="RESEARCH",
        infrastructure_status="HEALTHY", model_sha="m", feature_sha="f",
        last_durable_evidence_timestamp=None, uncertainty_enabled=True)
    assert d.mean_uncertainty_haircut == .01
    assert d.pct_edges_haircut == .5
