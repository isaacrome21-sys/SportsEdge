from datetime import date
import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_lineup_k_context as C
from sportsedge import mlb_lineup_k_context_research as R
from sportsedge.mlb_opp_k_context_research import OppIndex
from sportsedge.mlb_umpire_context_research import UStart
from sportsedge.pitcher_joint_engine import price_pitcher_market, PitcherJointEngineError
from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_empirical_support import support_evidence


def fixture():
    teams = {(t, y): [(f"{y}-04-01", 20 + t, 100)] for t in (1, 2) for y in (2024, 2025)}
    orders = {100+i: {2: tuple(range(10+i, 19+i))} for i in range(7)}
    batters = {b: [("2024-05-01", b, 100)] for b in range(10, 26)}
    idx, opp = R.LineupIndex(teams, batters), OppIndex(teams)
    own = [UStart(7, 2025, f"2025-05-{i+1:02d}", 100+i, 1, 2, k, 1)
           for i, k in enumerate([0, 3, 7, 12, 19, 24])]
    target = UStart(7, 2025, "2025-06-01", 106, 1, 2, 0, 0)
    orders[101][2] = None
    lane = {"W": 200.0, "gamma": 0.5, "target_deviation": R.deviation(target, orders, idx, opp, 200),
            "history_deviation": [R.deviation(x, orders, idx, opp, 200) or 1.0 for x in own],
            "validated_in": "#1540"}
    adj = {"market": "PITCHER_K", "beta": 1.0, "target_rel": opp.rel(2, 2025, target.date),
           "history_rel": [opp.rel(2, 2025, x.date) for x in own], "lineup_k_adjustment": lane}
    pool = [{"strikeouts": x.k, "outs": 18, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1} for x in own]
    return own, target, orders, idx, opp, {"history_pool": pool, "opp_k_adjustment": adj}


def test_engine_matches_frozen_selected_candidate_every_half_line():
    own, target, orders, idx, opp, features = fixture()
    expected = R.predict(own, target, orders, idx, opp, (200.0, 0.5))
    for i, line in enumerate(R.THRESH):
        for side in ("OVER", "UNDER"):
            out = price_pitcher_market({"market": "PITCHER_K", "side": side, "line": float(line), "features": features})
            assert out["model_p"] == pytest.approx(expected[i] if side == "OVER" else 1-expected[i], rel=0, abs=1e-12)
    assert hashlib.sha256((Path(__file__).parents[1]/"docs/MLB_LINEUP_K_CONTEXT_PREREG.md").read_bytes()).hexdigest().startswith("ef5d88be")


@pytest.mark.parametrize("market,line", [("PITCHER_K", 5), ("PITCHER_BB", 1.5), ("PITCHER_OUTS", 17.5), ("PITCHER_ER", 1.5)])
def test_scope_preserves_other_markets_and_integer_lines(market, line):
    *_, features = fixture()
    row = {"market": market, "side": "OVER", "line": line, "features": features}
    base = copy.deepcopy(row)
    base["features"].pop("opp_k_adjustment")
    assert price_pitcher_market(row)["model_p"] == price_pitcher_market(base)["model_p"]


def test_invalid_deviation_and_parameters_are_rejected():
    *_, features = fixture()
    for patch in ({"gamma": 1}, {"history_deviation": [1]}, {"target_deviation": float("nan")}, {"target_deviation": 0}):
        f = copy.deepcopy(features)
        f["opp_k_adjustment"]["lineup_k_adjustment"].update(patch)
        with pytest.raises(PitcherJointEngineError):
            price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 5.5, "features": f})


def test_support_and_card_note_bind_actual_adjustment():
    *_, features = fixture()
    row = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 5.5, "features": features})
    row.update(market="PITCHER_K", side="OVER", line=5.5, entity_id="7")
    row["empirical_evidence"] = support_evidence({"features": features}, row)
    assert row["empirical_evidence"]["lineup_k_adjustment"]["gamma"] == 0.5
    assert "LINEUP-K ADJ" in C.lineup_k_notes({"results": [row]})[0]


def test_missing_lineup_skips_history_and_failure_is_memoized(monkeypatch):
    source = MLBGenericHistorySource()
    calls = []
    def box(pk):
        calls.append(pk)
        return {"orders": {2: None}}
    monkeypatch.setattr(source, "_lineup_boxscore", box)
    kw = dict(game_pk=99, player_id=7, target_date=date(2026, 10, 4), opponent_id=2)
    assert source._lineup_k_payload(**kw) == (None, "opponent lineup not posted")
    assert source._lineup_k_payload(**kw) == (None, "opponent lineup not posted")
    assert calls == [99]


def test_adjustment_clips_after_both_factors():
    adj = {"beta": 1, "target_rel": 2, "history_rel": [1],
           "lineup_k_adjustment": {"W": 200, "gamma": .5, "target_deviation": .25, "history_deviation": [1]}}
    assert C.adjusted_values([15], adj) == [15]  # not clip(30)*.5 = 10


def test_native_source_payload_matches_research_and_excludes_future_counts(monkeypatch):
    source = MLBGenericHistorySource()
    own, target, orders, _, _, features = fixture()
    target_date = date.fromisoformat(target.date)
    teams = {(t, y): [(f"{y}-04-01", 20+t, 100)] for t in range(1, 31) for y in (2024, 2025)}
    batters = {b: [("2024-05-01", b, 100), ("2025-06-01", 50, 50), ("2025-10-01", 90, 100)]
               for b in range(10, 26)}
    def payload(rows):
        return {"stats": [{"splits": [{"date": d, "stat": {"strikeOuts": k, "plateAppearances": pa}}
                                      for d, k, pa in rows]}]}
    monkeypatch.setattr(source, "_lineup_boxscore", lambda pk: {"orders": orders[pk]})
    monkeypatch.setattr(source, "_pitcher_start_rows_pk", lambda **kw:
                        [(r, date.fromisoformat(x.date), x.opp_id, x.game_pk)
                         for r, x in zip(features["history_pool"], own)])
    opp = OppIndex(teams)
    monkeypatch.setattr(source, "opp_k_index", lambda d: opp)
    monkeypatch.setattr(source, "_mlb_team_ids", lambda y: list(range(1, 31)))
    monkeypatch.setattr(source, "_memo_team_season", lambda t, y: payload(teams[t, y]))
    monkeypatch.setattr(source, "_player_season", lambda b, group, y:
                        payload([x for x in batters[b] if int(x[0][:4]) == y]))
    lane = C.build_payload(source, game_pk=106, player_id=7, target_date=target_date, opponent_id=2)
    idx = R.LineupIndex(teams, batters)
    assert lane["target_deviation"] == pytest.approx(R.deviation(target, orders, idx, opp, 200))
    assert lane["history_deviation"] == pytest.approx([R.deviation(x, orders, idx, opp, 200) or 1 for x in own])
    prior = R.LineupIndex(teams, {b: rows[:1] for b, rows in batters.items()})
    assert lane["target_deviation"] == pytest.approx(R.deviation(target, orders, prior, opp, 200))
