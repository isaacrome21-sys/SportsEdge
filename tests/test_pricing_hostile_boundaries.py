"""Hostile-boundary regression tests for pricing math.

Reproductions from the Oct 27, 2026 adversarial pass: a config-shaped
``max_age_seconds`` (string / None) crashed check_quote_freshness with a
raw TypeError; find_paired_quote crashed on junk entries in the quote
list; _line_key coerced bool/string lines through float().
"""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.devig import DevigError, find_paired_quote, validate_pair
from sportsedge.quote_freshness import (
    QUOTE_FRESH,
    QUOTE_STALE,
    check_quote_freshness,
)

NOW = datetime(2026, 10, 27, 18, 0, 0, tzinfo=timezone.utc)


def _cap(age_s):
    return (NOW - timedelta(seconds=age_s)).isoformat()


def _q(side, odds, line=47.5, **kw):
    base = {"game_id": "g1", "market": "TOTAL", "entity_id": "g1",
            "side": side, "american_odds": odds, "line": line}
    base.update(kw)
    return base


# --- quote freshness caller-parameter boundary -----------------------------

@pytest.mark.parametrize("bad", ["180", "1800", None, True, 180.5, float("nan")])
def test_max_age_wrong_type_raises_named_value_error(bad):
    with pytest.raises(ValueError, match="QUOTE_FRESHNESS_MAX_AGE_INVALID"):
        check_quote_freshness(_cap(10), now=NOW, max_age_seconds=bad)


def test_max_age_integral_float_accepted():
    result = check_quote_freshness(_cap(10), now=NOW, max_age_seconds=1800.0)
    assert result["code"] == QUOTE_FRESH
    assert result["max_age_seconds"] == 1800


def test_now_wrong_type_raises_named_value_error():
    with pytest.raises(ValueError, match="QUOTE_FRESHNESS_NOW_INVALID"):
        check_quote_freshness(_cap(10), now="2026-10-27T18:00:00+00:00")


def test_freshness_boundaries_unchanged():
    assert check_quote_freshness(_cap(180), now=NOW)["code"] == QUOTE_FRESH
    assert check_quote_freshness(_cap(181), now=NOW)["code"] == QUOTE_STALE
    assert check_quote_freshness(_cap(1800), now=NOW,
                                 max_age_seconds=1800)["code"] == QUOTE_FRESH


# --- devig pairing boundary --------------------------------------------------

def test_find_paired_quote_skips_junk_entries():
    candidate = _q("OVER", -110)
    found = find_paired_quote(candidate, ["junk", None, 42, ["x"], _q("UNDER", -110)])
    assert found["side"] == "UNDER"


def test_find_paired_quote_junk_only_still_refuses_by_name():
    with pytest.raises(DevigError, match="PAIRED_PRICE_REQUIRED_FOR_DEVIG"):
        find_paired_quote(_q("OVER", -110), ["junk", None])


def test_find_paired_quote_non_mapping_candidate_refused_by_name():
    with pytest.raises(DevigError, match="identity incomplete"):
        find_paired_quote("junk", [_q("UNDER", -110)])


@pytest.mark.parametrize("bad_line", [True, "47.5", None, [47.5]])
def test_line_wrong_type_refused(bad_line):
    with pytest.raises(DevigError, match="paired quote line invalid"):
        validate_pair(_q("OVER", -110, line=bad_line), _q("UNDER", -110))


def test_numeric_line_forms_still_pair():
    validate_pair(_q("OVER", -110, line=47.5), _q("UNDER", -110, line=47.5))
    validate_pair(_q("OVER", -110, line=47), _q("UNDER", -110, line=47.0))
