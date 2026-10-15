"""Regression tests for DK main-line NFL yardage pairing, no implicit side."""
from datetime import datetime, timedelta, timezone
import pytest
from sportsedge.paired_yardage_intake import bind_nfl_yardage_pair, YardagePairRefusal

NOW = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)


def quote(**updates):
    q = dict(sport="NFL", market="RECEIVING_YARDS", book="DRAFTKINGS",
             game_id="game-1", player_id="player-1", team="SEA", capture_id="capture-1",
             player_name="Example Player", away="Seattle Seahawks", home="Denver Broncos", kickoff="2026-10-15T00:00:00Z",
             line=94.5, over_odds=-112, under_odds=-112, captured_at=NOW)
    q.update(updates)
    return q


def test_preserves_both_prices_and_identity():
    over, under = bind_nfl_yardage_pair(quote(over_odds=105, under_odds=-125), as_of=NOW)
    assert (over["side"], over["odds"], under["side"], under["odds"]) == ("OVER", 105, "UNDER", -125)
    assert over["game_id"] == under["game_id"] == "game-1"
    assert over["market"] == under["market"] == "PLAYER_RECEIVING_YARDS"
    assert over["quote_captured_at"] == under["quote_captured_at"] == NOW.isoformat()
    assert over["player_name"] == under["player_name"] == "Example Player"


@pytest.mark.parametrize("changes,reason", [
    ({"under_odds": None}, "INVALID_AMERICAN_ODDS"),
    ({"over_odds": None}, "INVALID_AMERICAN_ODDS"),
    ({"over_line": 93.5}, "PAIR_LINE_MISMATCH"),
    ({"under_game_id": "game-2"}, "PAIR_FIXTURE_MISMATCH"),
    ({"under_player_id": "player-2"}, "PAIR_PLAYER_MISMATCH"),
    ({"book": "OTHER"}, "NOT_DK_QUOTE"),
    ({"market": "INTERCEPTIONS"}, "NOT_NFL_YARDAGE_MAIN"),
    ({"captured_at": NOW + timedelta(seconds=1)}, "FUTURE_QUOTE"),
    ({"captured_at": NOW - timedelta(seconds=181)}, "STALE_QUOTE"),
    ({"captured_at": NOW.replace(tzinfo=None)}, "PIT_CAPTURE_TIME_REQUIRED"),
])
def test_refuses_untrustworthy_pairs(changes, reason):
    with pytest.raises(YardagePairRefusal, match=reason):
        bind_nfl_yardage_pair(quote(**changes), as_of=NOW)


def test_canonical_run_it_receives_both_sides_without_promotion():
    """Actual RUN IT entrypoint, offline: both quotes must reach the card."""
    from artifacts.run_it_full import run_full

    card = run_full(
        {"lines": [], "nfl_yardage_pairs": [quote()]},
        now=NOW, as_of=NOW.isoformat(), auto_context=False,
    )
    rows = card["evaluated_rows"]
    assert len(rows) == 2
    assert card["summary"]["rows"] == 2
    # Registry gates are preserved; no synthetic quote earns play authority.
    assert all(r.get("official_authority") is not True for r in rows)
    assert all(r.get("model_p_authority") is not True for r in rows)
    assert all(r.get("staking_authority") is not True for r in rows)
    assert card["research_only"] is True


def test_canonical_run_it_refuses_incomplete_pair_before_pricing():
    from artifacts.run_it_full import run_full

    with pytest.raises(YardagePairRefusal, match="INVALID_AMERICAN_ODDS"):
        run_full(
            {"lines": [], "nfl_yardage_pairs": [quote(under_odds=None)]},
            now=NOW, as_of=NOW.isoformat(), auto_context=False,
        )


def test_json_iso_capture_timestamp_preserved_and_routed():
    """CLI JSON capture timestamps must be accepted without timestamp rewrite."""
    from artifacts.run_it_full import run_full

    raw = "2026-10-14T18:00:00Z"
    pair = quote(captured_at=raw)
    over, under = bind_nfl_yardage_pair(pair, as_of=NOW)
    assert over["quote_captured_at"] == raw
    assert under["quote_captured_at"] == raw
    assert over["side"] == "OVER" and under["side"] == "UNDER"
    card = run_full(
        {"lines": [], "nfl_yardage_pairs": [pair]},
        now=NOW, as_of=NOW.isoformat(), auto_context=False,
    )
    assert len(card["evaluated_rows"]) == 2
    assert all(r.get("staking_authority") is not True for r in card["evaluated_rows"])


def test_naive_json_capture_timestamp_refuses():
    with pytest.raises(YardagePairRefusal, match="PIT_CAPTURE_TIME_REQUIRED"):
        bind_nfl_yardage_pair(
            quote(captured_at="2026-10-14T18:00:00"), as_of=NOW,
        )
