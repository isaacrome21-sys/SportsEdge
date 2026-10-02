import pytest

from sportsedge.sports.nfl.prop_market_history import (
    PropMarketHistoryError,
    bind_prop_decision_close,
    normalize_prop_snapshot,
)


def _base(market="RECEPTIONS", observed="2026-09-10T15:00:00+00:00"):
    row = {
        "game_id": "g1",
        "player_id": "p1",
        "market_id": market,
        "book": "DK",
        "observed_at": observed,
        "game_start": "2026-09-10T20:00:00+00:00",
        "primary_price": -110,
        "primary_side": "OVER",
        "line": 5.5,
        "opposite_price": -110,
    }
    if market == "ANYTIME_TD":
        row["primary_side"] = "YES"
        row["line"] = None
        row["opposite_price"] = None
    return row


def test_two_sided_prop_requires_paired_price_and_binds_close():
    decision = _base()
    close = _base(observed="2026-09-10T19:30:00+00:00")
    close["primary_price"] = -125
    close["opposite_price"] = 105
    pair = bind_prop_decision_close(decision, close)
    assert pair.market_id == "RECEPTIONS"
    assert pair.decision.no_vig_available is True
    assert pair.promotion_authority is False
    assert pair.reconstructed is False


def test_anytime_td_allows_one_sided_market_without_fake_novig():
    snap = normalize_prop_snapshot(_base("ANYTIME_TD"))
    assert snap.paired_market is False
    assert snap.no_vig_available is False
    assert snap.opposite_price is None


def test_reconstructed_or_post_start_snapshots_fail_closed():
    row = _base()
    row["reconstructed"] = True
    with pytest.raises(PropMarketHistoryError, match="RECONSTRUCTED_FORBIDDEN"):
        normalize_prop_snapshot(row)

    row = _base()
    row["observed_at"] = row["game_start"]
    with pytest.raises(PropMarketHistoryError, match="POST_START_SNAPSHOT"):
        normalize_prop_snapshot(row)


def test_threshold_or_book_identity_mismatch_fails():
    decision = _base()
    close = _base(observed="2026-09-10T19:30:00+00:00")
    close["line"] = 6.5
    with pytest.raises(PropMarketHistoryError, match="THRESHOLD_MISMATCH"):
        bind_prop_decision_close(decision, close)

    close = _base(observed="2026-09-10T19:30:00+00:00")
    close["book"] = "FD"
    with pytest.raises(PropMarketHistoryError, match="IDENTITY_MISMATCH"):
        bind_prop_decision_close(decision, close)
