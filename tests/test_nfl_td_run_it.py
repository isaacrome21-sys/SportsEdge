import pytest

from sportsedge.nfl_td_run_it import NflTdRunItError, price_anytime_td, rank_td_board

NOW = "2026-09-23T01:30:00Z"


def _q(selection, price, **kw):
    row = {"player":"A Player","game_id":"g1","selection":selection,"price_american":price,"book":"DraftKings","retrieved_at":NOW}
    row.update(kw)
    return row


def test_td_row_gets_fair_price_ev_and_score():
    p = price_anytime_td(player="A Player", game_id="g1", estimate_p=.50, yes_quote=_q("YES", 150), no_quote=_q("NO", -180), as_of=NOW)
    assert p.fair_american == 100
    assert p.ev_per_dollar == pytest.approx(.25)
    assert p.score_0_100 == 100
    assert p.score_label == "SPORTSEDGE_TRANSPARENT_EV_SCORE_V1"


def test_td_quotes_fail_closed_on_stale_and_identity_mismatch():
    with pytest.raises(NflTdRunItError, match="STALE"):
        price_anytime_td(player="A Player", game_id="g1", estimate_p=.4, yes_quote=_q("YES",150,retrieved_at="2026-09-23T01:26:00Z"), no_quote=_q("NO",-180,retrieved_at="2026-09-23T01:26:00Z"), as_of=NOW)
    with pytest.raises(NflTdRunItError, match="IDENTITY"):
        price_anytime_td(player="A Player", game_id="g1", estimate_p=.4, yes_quote=_q("YES",150,player="Other"), no_quote=_q("NO",-180), as_of=NOW)


def test_td_board_rank_is_economics_driven():
    a = price_anytime_td(player="A Player", game_id="g1", estimate_p=.50, yes_quote=_q("YES",150), no_quote=_q("NO",-180), as_of=NOW)
    bq=lambda side,price: {"player":"B Player","game_id":"g1","selection":side,"price_american":price,"book":"DraftKings","retrieved_at":NOW}
    b = price_anytime_td(player="B Player", game_id="g1", estimate_p=.40, yes_quote=bq("YES",150), no_quote=bq("NO",-180), as_of=NOW)
    assert rank_td_board([b,a])[0].player == "A Player"
