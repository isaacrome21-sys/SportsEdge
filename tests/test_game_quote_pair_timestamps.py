from datetime import datetime, timezone
import pytest
from artifacts import free_models as engine

NOW = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)


def row(side="OVER", **kw):
    return {"sport": "MLB", "away": "A", "home": "B", "market": "TOTAL",
            "side": side, "line": 8.5, "odds": -110,
            "book": "draftkings", "kickoff": "2026-10-14T00:00:00Z",
            "quote_captured_at": "2026-10-13T10:00:00Z", **kw}


def projections(rows):
    card = engine.run({"lines": rows}, now=NOW, auto_context=False)
    return [r["independent_projection"] for r in card["evaluated_rows"]]


@pytest.mark.parametrize("stamp,code", [
    (None, "MISSING_COUNTERPART_QUOTE_TIMESTAMP"),
    ("bad", "INVALID_PAIR_QUOTE_TIMESTAMP"),
    ("2026-10-13T10:00:00", "INVALID_PAIR_QUOTE_TIMESTAMP"),
    ("2026-10-13T09:57:59Z", "MISMATCHED_QUOTE_TIMESTAMPS"),
])
def test_missing_invalid_and_out_of_window_quotes_emit_no_pair(stamp, code):
    for p in projections([row(), row("UNDER", quote_captured_at=stamp)]):
        assert p["paired_market_status"] == code
        assert "market_no_vig_p" not in p


@pytest.mark.parametrize("stamp,skew", [
    ("2026-10-13T09:58:00Z", 120),
    ("2026-10-13T05:00:00-05:00", 0),
    ("2026-10-13T09:59:59Z", 1),
])
def test_aware_same_instant_or_within_window_pairs(stamp, skew):
    ps = projections([row(), row("UNDER", quote_captured_at=stamp)])
    assert all(p["paired_quote_skew_seconds"] == skew for p in ps)
    assert abs(sum(p["market_no_vig_p"] for p in ps) - 1) < 1e-6


def test_bare_inline_opposite_price_cannot_supply_pair_provenance():
    p = projections([row("AWAY", market="ML", opposite_odds=-110)])[0]
    assert p["paired_market_status"] == "MISSING_COUNTERPART_QUOTE_TIMESTAMP"
    assert "market_no_vig_p" not in p


@pytest.mark.parametrize("field,value", [
    ("period", "FIRST_5"), ("phase", "LIVE"),
    ("settlement_type", "THREE_WAY"), ("event_id", "different"),
    ("dk_event_id", "different"),
])
def test_contract_mismatch_cannot_pair(field, value):
    ps = projections([row(), row("UNDER", **{field: value})])
    assert all("market_no_vig_p" not in p for p in ps)
