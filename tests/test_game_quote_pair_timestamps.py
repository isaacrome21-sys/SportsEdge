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


@pytest.mark.parametrize("stamp,expected_codes", [
    (None, ("COUNTERPART_QUOTE_TIMESTAMP_MISSING", "QUOTE_TIMESTAMP_MISSING")),
    ("bad", ("INVALID_PAIR_QUOTE_TIMESTAMP", "INVALID_PAIR_QUOTE_TIMESTAMP")),
    ("2026-10-13T10:00:00", ("INVALID_PAIR_QUOTE_TIMESTAMP", "INVALID_PAIR_QUOTE_TIMESTAMP")),
    ("2026-10-13T09:57:59Z", ("MISMATCHED_QUOTE_TIMESTAMPS", "MISMATCHED_QUOTE_TIMESTAMPS")),
])
def test_missing_invalid_and_out_of_window_quotes_emit_no_pair(stamp, expected_codes):
    projections_for_pair = projections([row(), row("UNDER", quote_captured_at=stamp)])
    assert tuple(p["paired_market_status"] for p in projections_for_pair) == expected_codes
    assert all("market_no_vig_p" not in p for p in projections_for_pair)
    assert all("paired_quote_captured_at" not in p for p in projections_for_pair)


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
    assert p["paired_market_status"] == "OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE"
    assert "market_no_vig_p" not in p


@pytest.mark.parametrize("field,value", [
    ("period", "FIRST_5"), ("phase", "LIVE"), ("alternate", True),
    ("settlement_type", "THREE_WAY"), ("event_id", "different"),
    ("dk_event_id", "different"),
])
def test_contract_mismatch_cannot_pair(field, value):
    ps = projections([row(), row("UNDER", **{field: value})])
    assert all("market_no_vig_p" not in p for p in ps)


def test_successful_pair_proves_both_receipts_and_exact_contract():
    paired = projections([
        row(quote_captured_at="2026-10-13T10:00:00Z", alternate=False),
        row("UNDER", quote_captured_at="2026-10-13T09:59:00Z", alternate=False),
    ])
    assert all(p["paired_market_status"] == "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH" for p in paired)
    assert all(p["paired_quote_skew_seconds"] == 60 for p in paired)
    assert all(len(p["paired_quote_captured_at"]) == 2 for p in paired)
    assert abs(sum(p["market_no_vig_p"] for p in paired) - 1) < 1e-6
