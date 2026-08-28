import pytest

from sportsedge.devig import DevigError, multiplicative_devig


def _quote(side, odds, **updates):
    row = {
        "game_id": "g1",
        "period": "FG",
        "market": "TOTALS",
        "entity_id": "GAME",
        "book_key": "book",
        "is_alternate": False,
        "line": 8.5,
        "side": side,
        "american_odds": odds,
    }
    row.update(updates)
    return row


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None])
def test_devig_rejects_non_boolean_alternate_identity(bad):
    candidate = _quote("OVER", -110, is_alternate=bad)
    opposite = _quote("UNDER", -110, is_alternate=bad)
    with pytest.raises(DevigError, match="is_alternate must be bool"):
        multiplicative_devig(candidate, opposite)


def test_standard_boolean_identity_still_devigs_normally():
    result = multiplicative_devig(_quote("OVER", -110), _quote("UNDER", -110))
    assert result.candidate_fair_probability == pytest.approx(0.5)
    assert result.opposite_fair_probability == pytest.approx(0.5)
