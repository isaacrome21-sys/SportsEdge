import pytest
from sportsedge.pipeline.picks import PickRecord, PickRecordError, expected_value

def row(**kw):
    r=dict(sport="NFL",market="total",selection="OVER",line=45.5,dk_price=-110,captured_at="2026-10-25T12:00:00Z",model_p=.55,engine="test",ev=expected_value(.55,-110),ladder_status="PAPER")
    r.update(kw);return r

@pytest.mark.parametrize("span,tier",[(150,"FULL"),(150.01,"RESEARCH"),(300,"RESEARCH")])
def test_span_survives_serialization(span,tier):
    p=PickRecord.from_dict(row(span_seconds=span,capture_method="FALLBACK"))
    assert p.span_tier==tier
    assert PickRecord.from_dict(p.to_dict())==p

@pytest.mark.parametrize("kw",[dict(span_seconds=301),dict(span_seconds=True),dict(span_seconds=float("nan")),dict(span_seconds=200,span_tier="FULL"),dict(span_tier="FULL"),dict(span_seconds=200,ladder_status="STAKE_0_25U")])
def test_invalid_or_research_staking_refuses(kw):
    with pytest.raises(PickRecordError):PickRecord.from_dict(row(**kw))


def test_builder_to_shared_grader_keeps_research_metadata():
    from sportsedge.pipeline.picks import make_pick
    from sportsedge.pipeline.grading import grade, FinalResult, WIN
    data=row(span_seconds=200,capture_method="PRIMARY_BROWSER")
    data.pop("ev")
    pick=make_pick(**data)
    saved=pick.to_dict()
    assert saved["span_seconds"]==200 and saved["span_tier"]=="RESEARCH"
    assert saved["capture_method"]=="PRIMARY_BROWSER" and saved["ladder_status"]=="PAPER"
    assert grade(saved,FinalResult(away_score=25,home_score=25),family="total")==WIN
    restored=PickRecord.from_dict(saved)
    assert restored.span_tier=="RESEARCH" and restored.ladder_status=="PAPER"
