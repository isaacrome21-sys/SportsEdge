"""Opponent on-base index -> pitcher outs in production (#1482 D2a), validated in #1523.

The engine's adjusted outs price must equal the research ``predict_outs`` that passed
the pre-registered held-out test. Missing inputs keep the unadjusted price.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from sportsedge import mlb_opp_outs_context as C
from sportsedge import mlb_opp_outs_context_research as R
from sportsedge.mlb_empirical_support import support_evidence
from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_pitcher_prior_research import OUTS_THRESH
from sportsedge.pitcher_joint_engine import price_pitcher_market

ROOT = Path(__file__).resolve().parents[1]
TEAMS = list(range(101, 131))


def _team_log(team: int, season: int, n: int = 150, seed: int = 0) -> dict:
    rnd = random.Random(team * 7919 + season * 31 + seed)
    ob_rate = 0.28 + 0.08 * ((team * 37) % 30) / 29
    start = date(season, 3, 28)
    splits = []
    for g in range(n):
        pa = rnd.randint(33, 42)
        hits = sum(rnd.random() < ob_rate * 0.7 for _ in range(pa))
        bb = sum(rnd.random() < ob_rate * 0.25 for _ in range(pa))
        hbp = sum(rnd.random() < 0.01 for _ in range(pa))
        ks = sum(rnd.random() < 0.22 for _ in range(pa))
        splits.append({"date": (start + timedelta(days=g)).isoformat(), "stat": {
            "strikeOuts": ks, "hits": hits, "baseOnBalls": bb, "hitByPitch": hbp, "plateAppearances": pa,
        }})
    return {"stats": [{"splits": splits}]}


def _fetch(team: int, season: int) -> dict:
    return _team_log(team, season)


def _index(target: date):
    return C.build_index(_fetch, TEAMS, target)


def _own(n: int, seed: int) -> list[tuple[dict, date, int]]:
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        d = date(2025, 7, 1) + timedelta(days=9 * i)
        out.append(({"strikeouts": rnd.randint(0, 12), "outs": rnd.randint(9, 21), "earned_runs": 2,
                     "hits_allowed": 5, "walks_allowed": 1}, d, rnd.choice(TEAMS)))
    return out


def test_prereg_binding():
    sha = hashlib.sha256((ROOT / "docs/MLB_OPP_OUTS_CONTEXT_PREREG.md").read_bytes()).hexdigest()
    assert sha.startswith(C.PREREG_SHA256_PREFIX)
    assert C.BETA == -0.25 and C.INDEX == "obidx"
    assert (C.INDEX, C.BETA) in R.CANDIDATES


@pytest.mark.parametrize("n,seed", [(5, 1), (7, 2), (10, 3), (10, 4), (6, 5)])
def test_engine_equals_validated_research_predict_outs(n, seed):
    target_date = date(2026, 5, 20)
    index = _index(target_date)
    own = _own(n, seed)
    opp = TEAMS[seed]
    feats = {"history_pool": [r for r, _, _ in own],
             "opp_outs_adjustment": C.adjustment_features(index, target_opp_id=opp, target_date=target_date,
                                                          history=[(d, o) for _, d, o in own])}
    starts = [R.OStart(1, d.year, d.isoformat(), i, 1, o, r["outs"]) for i, (r, d, o) in enumerate(own)]
    target = R.OStart(1, 2026, target_date.isoformat(), 999, 1, opp, 0)
    research = R.predict_outs(starts, target, {"obidx": index}, (C.INDEX, C.BETA))
    baseline = R.predict_outs(starts, target, {"obidx": index}, ("base", 0.0))
    moved = False
    for i, line in enumerate(OUTS_THRESH):
        for side in ("OVER", "UNDER"):
            out = price_pitcher_market({"market": "PITCHER_OUTS", "side": side, "line": float(line), "features": feats})
            expected = research[i] if side == "OVER" else 1 - research[i]
            assert out["model_p"] == pytest.approx(float(expected), abs=1e-12)
            assert out["meta"]["effective_history_starts"] == n
            plain = price_pitcher_market({"market": "PITCHER_OUTS", "side": side, "line": float(line),
                                          "features": {"history_pool": feats["history_pool"]}})
            base = baseline[i] if side == "OVER" else 1 - baseline[i]
            assert plain["model_p"] == pytest.approx(float(base), abs=1e-12)
            moved = moved or abs(out["model_p"] - plain["model_p"]) > 1e-6
    assert moved


def test_scope_is_exactly_what_was_validated():
    target_date = date(2026, 5, 20)
    index = _index(target_date)
    own = _own(8, 9)
    pool = [r for r, _, _ in own]
    adj = C.adjustment_features(index, target_opp_id=TEAMS[0], target_date=target_date, history=[(d, o) for _, d, o in own])
    feats = {"history_pool": pool, "opp_outs_adjustment": adj}
    plain = {"history_pool": pool}
    for market, line in (("PITCHER_OUTS", 16.0), ("PITCHER_K", 5.5), ("PITCHER_BB", 1.5)):
        a = price_pitcher_market({"market": market, "side": "OVER", "line": line, "features": feats})
        b = price_pitcher_market({"market": market, "side": "OVER", "line": line, "features": plain})
        assert a["model_p"] == b["model_p"] and "opp_outs_adjustment" not in a["meta"]
    with pytest.raises(C.OppOutsContextError):
        C.adjustment_features(index, target_opp_id=TEAMS[0], target_date=target_date, history=[(d, o) for _, d, o in own[:4]])
    with pytest.raises(ValueError, match="align"):
        price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": 15.5,
                              "features": {"history_pool": pool, "opp_outs_adjustment": dict(adj, history_rel=adj["history_rel"][:-1])}})


class _Source(MLBGenericHistorySource):
    def __init__(self, n: int):
        super().__init__(opener=None)
        self.n = n

    def player_rows(self, *, player_id, group, target_date):
        return [{"date": date(2025, 4, 1) + timedelta(days=6 * i), "opponent_id": TEAMS[i % 30],
                 "stat": {"gamesStarted": 1, "inningsPitched": "5.1", "strikeOuts": 3 + i % 5,
                          "earnedRuns": 2, "hits": 4, "baseOnBalls": 1}}
                for i in range(self.n)]

    def _team_season(self, team_id, season):
        return _team_log(team_id, season)

    def _mlb_team_ids(self, season):
        return list(TEAMS)


def _row(src, market, team_id=TEAMS[2]):
    return src.feature_row(game_pk=1, market=market, entity_id="9", target_date=date(2026, 5, 20),
                           away_team_id=TEAMS[2], home_team_id=TEAMS[0], player_id=9, team_id=team_id)


def test_feature_payload_attaches_only_to_outs():
    src = _Source(8)
    outs = _row(src, "PITCHER_OUTS")
    assert outs["joint_feature_version"] == "mlb_pitcher_joint_history_opp_outs_v1"
    adj = outs["features"]["opp_outs_adjustment"]
    assert adj["market"] == "PITCHER_OUTS" and adj["index"] == "obidx" and adj["beta"] == -0.25
    assert "opp_outs_adjustment" not in _row(src, "PITCHER_K")["features"]
    assert _row(src, "PITCHER_OUTS", team_id=TEAMS[0])["features"]["opp_outs_adjustment"]["opponent_team_id"] == TEAMS[2]


def test_missing_input_keeps_unadjusted_price():
    src = _Source(8)
    src.player_rows = lambda **kwargs: [{"date": date(2025, 4, 1) + timedelta(days=6 * i), "opponent_id": None,
                                         "stat": {"gamesStarted": 1, "inningsPitched": "5.1", "strikeOuts": 3,
                                                  "earnedRuns": 2, "hits": 4, "baseOnBalls": 1}} for i in range(8)]
    row = _row(src, "PITCHER_OUTS")
    assert "opp_outs_adjustment" not in row["features"]
    why = row["opp_outs_unadjusted"]
    out = price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": 15.5, "features": row["features"]})
    ref = price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": 15.5,
                                "features": {"history_pool": row["features"]["history_pool"]}})
    assert out["model_p"] == ref["model_p"]
    ev = support_evidence(row, {**out, "american_odds": -110, "engine_version": "mlb_pitcher_joint_empirical_v1"})
    assert why in ev["opp_outs_unadjusted"]


def test_shared_team_log_fetch_and_card_note():
    calls = []
    src = _Source(8)
    orig = src._team_season
    src._team_season = lambda t, s: (calls.append((t, s)), orig(t, s))[1]
    _row(src, "PITCHER_K")
    _row(src, "PITCHER_OUTS")
    assert len(calls) == 90
    row = _row(src, "PITCHER_OUTS")
    half = price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": 15.5, "features": row["features"]})
    whole = price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": 16.0, "features": row["features"]})
    ev = support_evidence(row, {**half, "american_odds": -110, "engine_version": "mlb_pitcher_joint_empirical_v1"})
    assert ev["opp_outs_adjustment"]["own_starts"] == 8
    assert "integer line" in support_evidence(row, {**whole, "american_odds": -110, "engine_version": "mlb_pitcher_joint_empirical_v1"})["opp_outs_unadjusted"]
    notes = C.opp_outs_notes({"results": [{"entity_id": "9", "market": "PITCHER_OUTS", "empirical_evidence": ev}]}, {"9": "Tarik Skubal"})
    assert notes[0].startswith(f"OPP-OUTS ADJ x{ev['opp_outs_adjustment']['factor']:.2f} Tarik Skubal Pitcher outs:")
    assert "LEAN max" in notes[0]
