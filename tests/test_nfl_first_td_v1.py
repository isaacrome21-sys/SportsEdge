"""NFL_FIRST_TD_V1 construction tests (design-stage, UNPINNED).

Covers the design's pinned forms (DESIGN_NFL_GAME_PROPS_TD_V1.md
section 2): Part 2 K = 3 shrinkage at both levels, the DEF/ST pooled
class, the no-TD outcome, renormalization over board + DEF/ST +
no-TD, and point-in-time isolation (a game's own data never enters
its own price; future games never change a past distribution).
"""
import math

import pytest

from sportsedge.nfl_first_td_v1 import (
    History,
    Pools,
    predict_b1,
    predict_b2,
    predict_v1,
    position_group,
)

CANDS = {
    "KC": [("00-0030001", "RB"), ("00-0030002", "WR"),
           ("00-0030003", "QB")],
    "BUF": [("00-0031001", "WR"), ("00-0031002", "TE")],
}


def _hist_with_games() -> History:
    h = History()
    # Three prior games: KC scores first twice (RB once, WR once),
    # BUF once (defensive). KC anytime TDs: RB x3, WR x2, QB x1.
    h.update_game(
        home="KC", away="BUF",
        first_td=("00-0030001", "KC", "RUSHING", "RB"),
        td_credits=[("00-0030001", "KC", "RUSHING", "RB"),
                    ("00-0030002", "KC", "RECEIVING", "WR"),
                    ("00-0030001", "KC", "RUSHING", "RB")])
    h.update_game(
        home="BUF", away="KC",
        first_td=("00-0039999", "BUF", "INTERCEPTION_RETURN", "OTHER"),
        td_credits=[("00-0039999", "BUF", "INTERCEPTION_RETURN", "OTHER"),
                    ("00-0030003", "KC", "RUSHING", "QB")])
    h.update_game(
        home="KC", away="BUF",
        first_td=("00-0030002", "KC", "RECEIVING", "WR"),
        td_credits=[("00-0030002", "KC", "RECEIVING", "WR"),
                    ("00-0030001", "KC", "RUSHING", "RB")])
    # A no-TD game, so the no-TD outcome carries sample mass.
    h.update_game(home="BUF", away="KC", first_td=None, td_credits=[])
    return h


def test_position_group_mapping():
    assert position_group("QB") == "QB"
    assert position_group("RB") == "RB"
    assert position_group("FB") == "RB"
    assert position_group("WR") == "WR"
    assert position_group("TE") == "TE"
    assert position_group("CB") == "OTHER"
    assert position_group(None) == "OTHER"
    assert position_group("") == "OTHER"


def test_distributions_sum_to_one():
    h = _hist_with_games()
    pools = h.pools()
    for dist in (predict_v1(h, pools, "KC", "BUF", CANDS),
                 predict_b1(h, pools, "KC", "BUF", CANDS),
                 predict_b2(pools, "KC", "BUF", CANDS)):
        assert abs(sum(dist.values()) - 1.0) < 1e-9
        assert dist["NO_TD"] > 0
        assert dist["DEFST:KC"] > 0 and dist["DEFST:BUF"] > 0


def test_stage1_shrinkage_form():
    # Team with no sample gets the league rate (Part 2 K form):
    # (0 + 3G) / (0 + 3) = G, so two unsampled teams split the
    # non-noTD mass evenly.
    h = History()
    pools = Pools(games=200, no_td_rate=0.10, team_first_rate=0.45,
                  first_pos={"QB": .1, "RB": .4, "WR": .35, "TE": .1,
                             "OTHER": .05},
                  any_pos={"QB": .1, "RB": .4, "WR": .35, "TE": .1,
                           "OTHER": .05},
                  def_any_share=0.05, def_first_share=0.05)
    dist = predict_v1(h, pools, "KC", "BUF", CANDS)
    kc = sum(v for k, v in dist.items()
             if k.startswith(("P:00-0030", "DEFST:KC")))
    assert kc == pytest.approx(0.45, abs=1e-9)
    assert dist["NO_TD"] == pytest.approx(0.10, abs=1e-9)


def test_first_td_history_moves_stage2():
    h = _hist_with_games()
    pools = h.pools()
    dist = predict_v1(h, pools, "KC", "BUF", CANDS)
    # The RB scored 2 of KC's 3 first TDs in sample and owns the
    # largest anytime share: he must carry KC's largest player mass.
    kc_players = {k: v for k, v in dist.items()
                  if k.startswith("P:00-0030")}
    assert max(kc_players, key=kc_players.get) == "P:00-0030001"


def test_b1_ignores_first_td_counts():
    # B1 collapses stage 2 to anytime shares: two histories with the
    # same anytime totals but different first-TD splits price alike.
    def build(first_pid):
        h = History()
        h.update_game(
            home="KC", away="BUF",
            first_td=(first_pid, "KC", "RECEIVING", "WR"),
            td_credits=[("00-0030001", "KC", "RUSHING", "RB"),
                        ("00-0030002", "KC", "RECEIVING", "WR")])
        return h
    pools = build("00-0030001").pools()
    d_a = predict_b1(build("00-0030001"), pools, "KC", "BUF", CANDS)
    d_b = predict_b1(build("00-0030002"), pools, "KC", "BUF", CANDS)
    assert d_a == pytest.approx(d_b)


def test_pit_isolation_future_game_does_not_change_past_price():
    h = _hist_with_games()
    pools = h.pools()
    before = predict_v1(h, pools, "KC", "BUF", CANDS)
    h.update_game(
        home="KC", away="BUF",
        first_td=("00-0031001", "BUF", "RECEIVING", "WR"),
        td_credits=[("00-0031001", "BUF", "RECEIVING", "WR")])
    # Recompute the SAME pre-game distribution from a fresh history
    # folded only with the original games: identical by construction
    # of the API (predict reads only the history it is given).
    h2 = _hist_with_games()
    after = predict_v1(h2, h2.pools(), "KC", "BUF", CANDS)
    assert before == after
    # And the post-game state does move the next price.
    moved = predict_v1(h, h.pools(), "KC", "BUF", CANDS)
    assert moved != before


def test_no_market_input_surface():
    # The construction's predict functions take no price/odds
    # argument anywhere (design: no market input).
    import inspect
    for fn in (predict_v1, predict_b1, predict_b2):
        params = set(inspect.signature(fn).parameters)
        assert not ({"price", "odds", "line"} & params)


def test_log_loss_finite_for_rostered_scorers():
    # With a pool carrying positive mass in every position group
    # (the real panel's pools always do), every rostered candidate
    # receives positive probability: the two-level shrinkage never
    # stakes an exact zero on a board player.
    h = _hist_with_games()
    pools = Pools(games=200, no_td_rate=0.02, team_first_rate=0.49,
                  first_pos={"QB": .08, "RB": .37, "WR": .38,
                             "TE": .13, "OTHER": .04},
                  any_pos={"QB": .09, "RB": .36, "WR": .38,
                           "TE": .13, "OTHER": .04},
                  def_any_share=0.05, def_first_share=0.05)
    dist = predict_v1(h, pools, "KC", "BUF", CANDS)
    for key, p in dist.items():
        assert p > 0, key
        assert math.isfinite(-math.log(p))
