from datetime import datetime, timedelta, timezone
from sportsedge.sports.nba.training import NBATrainingRow
from sportsedge.sports.nba.pace_efficiency import fit_pace_efficiency
from sportsedge.sports.nba.evaluation import evaluate_holdout

UTC=timezone.utc

def row(i,hp,ap):
    tip=datetime(2025,1,i,1,tzinfo=UTC)
    return NBATrainingRow(str(i),tip,tip-timedelta(hours=2),"H","A",100,114,112,113,111,hp,ap,"v1")

def test_holdout_metrics_are_deterministic_and_provenanced():
    model=fit_pace_efficiency([row(1,120,110),row(2,115,118)])
    a=evaluate_holdout(model,[row(3,108,105),row(4,121,117)])
    b=evaluate_holdout(model,[row(4,121,117),row(3,108,105)])
    assert a == b
    assert a.games == 2 and len(a.validation_sha256) == 64
    assert a.margin_mae >= 0 and a.total_mae >= 0

def test_holdout_requires_rows():
    import pytest
    model=fit_pace_efficiency([row(1,120,110),row(2,115,118)])
    with pytest.raises(ValueError,match="validation rows"):
        evaluate_holdout(model,[])
