"""Offline tests: NFL auto ticket -> composite intake conversion."""
import pytest

from scripts.nfl_ticket_to_composite_lines import TicketRefusal, convert

STAMP = "2026-10-18T15:19:30+00:00"


def _ticket(markets):
    return {"sport": "NFL", "games": [{"away": "Kansas City Chiefs", "home": "Las Vegas Raiders",
            "commence_time": "2026-10-18T20:05:00Z", "markets": markets}]}


def _m(kind, line, a, h):
    return {"market": kind, "line": line, "away_or_over_price": a, "home_or_under_price": h,
            "quote_retrieved_at": STAMP, "quote_timestamp_source": "PROVIDER_LAST_UPDATE"}


def test_all_three_markets_emit_both_sides_verbatim():
    rows = convert(_ticket([_m("moneyline", None, -180, 150), _m("spread", -3.5, -110, -110),
                            _m("total", 44.5, -108, -112)]))["lines"]
    got = {(r["market"], r["side"]): (r["odds"], r.get("line")) for r in rows}
    assert got == {("ML", "AWAY"): (-180, None), ("ML", "HOME"): (150, None),
                   ("SPREAD", "AWAY"): (-110, -3.5), ("SPREAD", "HOME"): (-110, 3.5),
                   ("TOTAL", "OVER"): (-108, 44.5), ("TOTAL", "UNDER"): (-112, 44.5)}
    assert {r["quote_captured_at"] for r in rows} == {STAMP}  # never re-dated


@pytest.mark.parametrize("bad, code", [
    (_m("total", 44.5, None, -110), "TICKET_MARKET_NOT_TWO_SIDED"),
    (dict(_m("total", 44.5, -110, -110), quote_retrieved_at=None), "TICKET_QUOTE_STAMP_MISSING"),
    (_m("spread", None, -110, -110), "TICKET_SPREAD_LINE_MISSING"),
    (_m("player_props", 1, -110, -110), "TICKET_MARKET_UNSUPPORTED"),
])
def test_incomplete_markets_refuse_never_half_emit(bad, code):
    with pytest.raises(TicketRefusal, match=code):
        convert(_ticket([bad]))


def test_non_nfl_and_empty_refuse():
    with pytest.raises(TicketRefusal, match="TICKET_SPORT_NOT_NFL"):
        convert({"sport": "CFB", "games": []})
    with pytest.raises(TicketRefusal, match="TICKET_EMPTY"):
        convert(_ticket([]))
