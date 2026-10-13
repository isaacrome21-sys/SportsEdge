"""A row's own opposite_odds field is not a timestamped counterpart quote (MLB run machine)."""
from sportsedge.mlb_quote_pairing import pair_opposite_odds
from sportsedge.mlb_edge_score import score_mlb_edge


def _row(side, odds, ts, opp=None):
    r = {"game_id": "G1", "market": "MONEYLINE", "entity_id": "", "book_key": "draftkings",
         "side": side, "team_side": side, "american_odds": odds, "quote_retrieved_at": ts}
    if opp is not None:
        r["opposite_odds"] = opp
    return r


def test_single_row_asserted_opposite_is_refused():
    out = pair_opposite_odds([_row("HOME", 120, "2026-10-13T12:00:00Z", opp=-140)])
    assert out[0]["opposite_odds"] is None
    assert out[0]["opposite_odds_refused"] == "OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE"
    scored = score_mlb_edge(model_p=0.6, american_odds=120, opposite_odds=out[0]["opposite_odds"])
    assert scored.status == "BLOCKED" and scored.market_p is None and scored.edge is None
