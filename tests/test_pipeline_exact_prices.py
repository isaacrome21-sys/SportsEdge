import pytest
from sportsedge.pipeline.picks import PickRecord, PickRecordError, make_pick, expected_value

BAD = [100.9, -110.9, 100.0, "100", "-110", True, None, float("nan"), float("inf")]

def row(**over):
    r = dict(sport="NFL", market="total", selection="OVER", line=47.5,
             dk_price=-110, captured_at="2026-10-25T12:00:00-05:00", model_p=.55,
             engine="test", ev=expected_value(.55,-110), ladder_status="PAPER")
    r.update(over)
    return r

@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("field", ["dk_price", "opposite_price"])
def test_roundtrip_rejects_changed_price_types(bad, field):
    if field == "opposite_price" and bad is None:
        return  # optional absent opposite quote stays absent
    with pytest.raises(PickRecordError):
        PickRecord.from_dict(row(**{field:bad}))

@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("field", ["dk_price", "opposite_price"])
def test_builder_rejects_before_price_coercion(bad, field):
    r=row(**{field:bad});r.pop("ev")
    if field == "opposite_price" and bad is None:
        return  # optional absent opposite quote stays absent
    with pytest.raises(PickRecordError):
        make_pick(**r)

@pytest.mark.parametrize("price", [-165,-110,100,125])
def test_exact_integer_quote_preserved(price):
    r=row(dk_price=price,opposite_price=-110,ev=expected_value(.55,price))
    assert PickRecord.from_dict(r).to_dict()["dk_price"] == price
