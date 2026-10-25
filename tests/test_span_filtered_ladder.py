from sportsedge.pipeline.ladder import span_filtered_evidence_supports, PAPER
from sportsedge.pipeline.picks import make_pick

def record(span=100, **kw):
    p=make_pick(sport='NFL',market='total',selection='OVER',line=45.5,dk_price=-110,captured_at='2026-10-25T12:00:00Z',model_p=.55,engine='v1',ladder_status='PAPER',span_seconds=span,capture_method='FALLBACK').to_dict()
    p.update(clv_prob=.01,units=.1);p.update(kw);return p

def test_research_does_not_make_fiftieth_pick():
    assert span_filtered_evidence_supports([record() for _ in range(49)]+[record(200)])==PAPER

def test_research_cannot_turn_losing_full_cohort_positive():
    assert span_filtered_evidence_supports([record(units=-1) for _ in range(50)]+[record(200,units=1000) for _ in range(100)])==PAPER

def test_missing_provenance_and_mixed_markets_stay_paper():
    assert span_filtered_evidence_supports([record(capture_method=None) for _ in range(50)])==PAPER
    assert span_filtered_evidence_supports([record() for _ in range(50)]+[record(market='spread')])==PAPER

def test_fifty_full_rows_only_report_support_not_promotion():
    assert span_filtered_evidence_supports([record() for _ in range(50)])=='STAKE_0_25U'
