from sportsedge.mlb_truth_gate_eval import evaluate_truth_gate


def test_gate_metrics_split_accept_reject_and_clv():
    rows = [
        {"gate_decision": "BET", "clv": .03},
        {"gate_decision": "BET", "clv": -.01},
        {"gate_decision": "PASS", "clv": -.04},
        {"gate_decision": "PASS", "clv": .02},
    ]
    m = evaluate_truth_gate(rows, minimum_n=1, tier_monotonicity_score=1.0)
    assert m.n_accepted == 2 and m.n_rejected == 2
    assert m.accepted_mean_clv == .01
    assert m.rejected_mean_clv == -.01
    assert m.avoided_bad_bets_rate == .5
    assert m.good_pass_false_negative_rate == .5
    assert m.clv_delta == .02
    assert m.quality_score is not None


def test_missing_close_excluded_from_clv_metrics():
    m = evaluate_truth_gate([
        {"gate_decision": "BET", "clv": None},
        {"gate_decision": "PASS", "clv": -.02},
    ])
    assert m.n_with_clv == 1
    assert m.accepted_mean_clv is None


def test_score_requires_minimum_sample():
    rows = [{"gate_decision": "PASS", "clv": -.02}] * 20 + [{"gate_decision": "BET", "clv": .02}] * 20
    m = evaluate_truth_gate(rows, minimum_n=300, tier_monotonicity_score=1.0)
    assert m.status == "INSUFFICIENT_EVIDENCE"
    assert m.quality_score is None


def test_unverified_price_is_rejected_counterfactual():
    m = evaluate_truth_gate([{"gate_decision": "UNVERIFIED_PRICE", "clv": -.01}])
    assert m.n_rejected == 1
