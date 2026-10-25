from datetime import datetime, timezone
from sportsedge.nfl_phone_player_pricing import phone_nfl_player_rows
from tests.test_milestone_ladder_ingestion_20261014 import (
    _stafford_ladder_row, _nfl_getter, NFL_AS_OF)


def pair():
    base = _stafford_ladder_row()
    base.pop("milestone_ladder", None)
    base.update(market="PLAYER_PASSING_YARDS", line=250.5, odds=-110)
    base["captured_at"] = base.pop("quote_captured_at")
    return [{**base, "side": side} for side in ("OVER", "UNDER")]


def test_captured_at_alias_retains_actual_quote_clock():
    rows = pair()
    for row in rows:
        row["captured_at"] = NFL_AS_OF.isoformat()
    out, _ = phone_nfl_player_rows(rows, now=NFL_AS_OF, getter=_nfl_getter)
    assert len(out) == 2
    assert all("ev_per_dollar" in r for r in out), out
    assert all(r["quote_status"] == "RECENT_CAPTURED_QUOTE" for r in out)
    assert all(r["staking_authority"] is False for r in out)


def test_capture_alias_does_not_refresh_stale_quotes():
    rows = pair()
    for row in rows:
        row["captured_at"] = "2026-10-01T00:00:00Z"
    out, _ = phone_nfl_player_rows(rows, now=NFL_AS_OF, getter=_nfl_getter)
    assert all(r.get("quote_status") == "STALE_QUOTE" for r in out), out


def test_explicit_quote_timestamp_keeps_precedence():
    rows = pair()
    for row in rows:
        row["captured_at"] = NFL_AS_OF.isoformat()
        row["quote_captured_at"] = "2026-10-01T00:00:00Z"
    out, _ = phone_nfl_player_rows(rows, now=NFL_AS_OF, getter=_nfl_getter)
    assert all(r.get("quote_status") == "STALE_QUOTE" for r in out), out
