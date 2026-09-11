import math

from sportsedge.mlb_market_monitor import assess_market_drift, edge_bucket_report, market_metrics


def _rows(ps, ys, market="NRFI", fair=.50):
    return [
        {
            "market": market,
            "model_probability": p,
            "outcome": y,
            "fair_market_probability": fair,
        }
        for p, y in zip(ps, ys)
    ]


def test_market_metrics_basic():
    rows = _rows([.60, .40], [1, 0])
    m = market_metrics(rows, market="NRFI")
    assert m.n == 2
    assert math.isclose(m.brier, .16, rel_tol=1e-9)
    assert math.isclose(m.mean_model_probability, .50, rel_tol=1e-9)
    assert math.isclose(m.outcome_rate, .50, rel_tol=1e-9)
    assert math.isclose(m.mean_edge, 0.0, rel_tol=1e-9)


def test_drift_quarantines_when_both_scores_degrade():
    prior = _rows([.80] * 60, [1] * 60)
    recent = _rows([.80] * 40, [0] * 40)
    d = assess_market_drift(prior + recent, market="NRFI", recent_n=40, prior_n=60,
                            minimum_recent=30, minimum_prior=50,
                            brier_tolerance=.01, logloss_tolerance=.02)
    assert d.status == "QUARANTINE_RESEARCH"
    assert d.brier_delta > 0
    assert d.logloss_delta > 0


def test_drift_requires_sample():
    rows = _rows([.6] * 20, [1] * 20)
    d = assess_market_drift(rows, market="NRFI")
    assert d.status == "INSUFFICIENT_EVIDENCE"


def test_edge_bucket_report_separates_ranges():
    rows = [
        {"market":"NRFI","model_probability":.51,"fair_market_probability":.50,"outcome":1},
        {"market":"NRFI","model_probability":.53,"fair_market_probability":.50,"outcome":1},
        {"market":"NRFI","model_probability":.56,"fair_market_probability":.50,"outcome":0},
        {"market":"NRFI","model_probability":.60,"fair_market_probability":.50,"outcome":1},
    ]
    report = edge_bucket_report(rows)
    assert [r["n"] for r in report] == [1, 1, 1, 1]
