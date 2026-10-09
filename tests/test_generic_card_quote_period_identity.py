"""Canonical MLB card quote identity must preserve the source period.

Regression: the sportsbook quote bridge and devig pair validator both include
period. Dropping it from card deduplication loses valid market rows.
"""
from types import SimpleNamespace

from sportsedge.generic_card_pipeline import _quote_key, _validated_quotes


def _offer(period):
    return {
        "game_id": "123", "market": "F5_TOTALS", "entity_id": "game",
        "period": period, "side": "OVER", "line": 4.5,
        "book_key": "dk", "is_alternate": False, "raw_market_name": "First 5 Total",
        "american_odds": -110, "retrieved_at": "2026-10-09T11:00:00+00:00",
    }


def test_distinct_canonical_periods_have_distinct_card_quote_keys():
    from sportsedge.quote_bridge import validate_canonical_quote
    fg = validate_canonical_quote(_offer("FG"))
    f5 = validate_canonical_quote(_offer("F5"))
    assert _quote_key(fg) != _quote_key(f5)


def test_validated_quote_index_keeps_period_identity():
    quotes = [_offer("FG"), _offer("F5"), _offer("FG")]
    indexed = _validated_quotes(quotes, {"123": SimpleNamespace(game_pk=123)})
    assert len(indexed) == 2
    assert {q["period"] for q in indexed} == {"FG", "F5"}
