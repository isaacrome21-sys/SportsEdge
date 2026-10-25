"""Owner 30-minute CFB quote TTL: boundary, missing, future and NFL parity."""
from datetime import timedelta
import pytest
from tests.test_contract_repairs_20261011 import model, NOW, row


@pytest.mark.parametrize("age,expected", [
    (180, "QUOTE_FRESH_UNDER_180S"),
    (1800, "QUOTE_FRESH_UNDER_180S"),
    (1801, "QUOTE_STALE_OVER_180S"),
    (-1, "QUOTE_TIMESTAMP_IN_FUTURE"),
])
def test_cfb_quote_ttl(age, expected):
    r = row(sport="CFB", away="Away", home="Home", market="TOTAL",
            side="OVER", line=47.5)
    r["quote_captured_at"] = (NOW - timedelta(seconds=age)).isoformat()
    result = model.calculate(r, model.PublicContext(NOW), NOW, auto_context=False)
    q = result["quote_freshness"]
    assert q["code"] == expected
    assert q["max_age_seconds"] == 1800


def test_cfb_missing_quote_still_unverified():
    r = row(sport="CFB", away="Away", home="Home", market="TOTAL",
            side="OVER", line=47.5)
    r.pop("quote_captured_at", None)
    result = model.calculate(r, model.PublicContext(NOW), NOW, auto_context=False)
    assert result["quote_freshness"]["code"] == "QUOTE_FRESHNESS_UNVERIFIED"


def test_nfl_existing_180_second_bound_unchanged():
    r = row(sport="NFL", away="Away", home="Home", market="TOTAL",
            side="OVER", line=47.5)
    r["quote_captured_at"] = (NOW - timedelta(seconds=181)).isoformat()
    result = model.calculate(r, model.PublicContext(NOW), NOW, auto_context=False)
    assert result["quote_freshness"]["max_age_seconds"] == 180
    assert result["quote_freshness"]["code"] == "QUOTE_STALE_OVER_180S"
