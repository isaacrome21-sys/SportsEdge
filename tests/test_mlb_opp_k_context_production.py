"""Opponent-K context lane in production (#1482 D1b), validated in #1509.

The engine's adjusted K price must equal the research ``predict_k`` that passed the
pre-registered held-out test, the scope must stay exactly what was validated, and any
missing input must fall back to the unadjusted price (never BLOCKED, never invented).
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from sportsedge import mlb_opp_k_context as C
from sportsedge import mlb_opp_k_context_research as O
from sportsedge.mlb_empirical_support import support_evidence
from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_history_cache import MLBHistoryCachedOpener
from sportsedge.pitcher_joint_engine import price_pitcher_market

ROOT = Path(__file__).resolve().parents[1]
TEAMS = list(range(101, 131))


def _team_log(team: int, season: int, n: int = 150, seed: int = 0) -> dict:
    """Synthetic StatsAPI team hitting gameLog with a team-specific K rate."""
    rnd = random.Random(team * 7919 + season * 31 + seed)
    rate = 0.18 + 0.08 * ((team * 37) % 30) / 29
    start = date(season, 3, 28)
    splits = []
    for g in range(n):
        pa = rnd.randint(33, 42)
        ks = sum(rnd.random() < rate for _ in range(pa))
        splits.append({"date": (start + timedelta(days=g)).isoformat(), "stat": {"strikeOuts": ks, "plateAppearances": pa}})
    return {"stats": [{"splits": splits}]}


def _fetch(team: int, season: int) -> dict:
    return _team_log(team, season)


def _index(target: date) -> O.OppIndex:
    return C.build_index(_fetch, TEAMS, target, workers=2)


def _own(n: int, seed: int) -> list[tuple[dict, date, int]]:
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        d = date(2025, 7, 1) + timedelta(days=9 * i)
        out.append(({"strikeouts": rnd.randint(0, 12), "outs": rnd.randint(9, 21), "earned_runs": 2,
                     "hits_allowed": 5, "walks_allowed": 1}, d, rnd.choice(TEAMS)))
    return out


def test_prereg_binding():
    sha = hashlib.sha256((ROOT / "docs/MLB_OPP_K_CONTEXT_PREREG.md").read_bytes()).hexdigest()
    assert sha.startswith(C.PREREG_SHA256_PREFIX)
    assert C.BETA == 1.0 and C.BETA in O.BETAS


@pytest.mark.parametrize("n,seed", [(5, 1), (7, 2), (10, 3), (10, 4), (6, 5)])
def test_engine_equals_validated_research_predict(n, seed):
    target_date = date(2026, 5, 20)
    index = _index(target_date)
    own = _own(n, seed)
    opp = TEAMS[seed]
    feats = {"history_pool": [r for r, _, _ in own],
             "opp_k_adjustment": C.adjustment_features(index, target_opp_id=opp, target_date=target_date,
                                                       history=[(d, o) for _, d, o in own])}
    starts = [O.KStart(1, d.year, d.isoformat(), i, 1, o, r["strikeouts"]) for i, (r, d, o) in enumerate(own)]
    target = O.KStart(1, 2026, target_date.isoformat(), 999, 1, opp, 0)
    research = O.predict_k(starts, target, index, C.BETA)
    baseline = O.predict_k(starts, target, index, 0.0)
    moved = False
    for i, line in enumerate(O.K_THRESH):
        for side in ("OVER", "UNDER"):
            out = price_pitcher_market({"market": "PITCHER_K", "side": side, "line": float(line), "features": feats})
            expected = research[i] if side == "OVER" else 1 - research[i]
            assert out["model_p"] == pytest.approx(expected, abs=1e-12)
            assert out["meta"]["effective_history_starts"] == n  # explicit n = k, no Kish shrinkage
            plain = price_pitcher_market({"market": "PITCHER_K", "side": side, "line": float(line),
                                          "features": {"history_pool": feats["history_pool"]}})
            base = baseline[i] if side == "OVER" else 1 - baseline[i]
            assert plain["model_p"] == pytest.approx(base, abs=1e-12)
            moved = moved or abs(out["model_p"] - plain["model_p"]) > 1e-6
    assert moved


def test_scope_is_exactly_what_was_validated():
    target_date = date(2026, 5, 20)
    index = _index(target_date)
    own = _own(8, 9)
    pool = [r for r, _, _ in own]
    adj = C.adjustment_features(index, target_opp_id=TEAMS[0], target_date=target_date, history=[(d, o) for _, d, o in own])
    feats = {"history_pool": pool, "opp_k_adjustment": adj}
    plain = {"history_pool": pool}
    # Integer K lines and every other market are priced exactly as before.
    for market, line in (("PITCHER_K", 5.0), ("PITCHER_OUTS", 15.5), ("PITCHER_BB", 1.5)):
        a = price_pitcher_market({"market": market, "side": "OVER", "line": line, "features": feats})
        b = price_pitcher_market({"market": market, "side": "OVER", "line": line, "features": plain})
        assert a["model_p"] == b["model_p"] and "opp_k_adjustment" not in a["meta"]
    with pytest.raises(C.OppKContextError):
        C.adjustment_features(index, target_opp_id=TEAMS[0], target_date=target_date, history=[(d, o) for _, d, o in own[:4]])
    with pytest.raises(C.OppKContextError):
        C.build_index(_fetch, TEAMS[:29], target_date)
    bad = dict(adj, history_rel=adj["history_rel"][:-1])
    with pytest.raises(ValueError, match="align"):
        price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 4.5, "features": {"history_pool": pool, "opp_k_adjustment": bad}})


def test_index_is_strictly_prior():
    a = _index(date(2026, 5, 20))
    # A game on the target date itself must not move rel() for that date.
    def fetch_plus(team: int, season: int) -> dict:
        log = _team_log(team, season)
        if season == 2026:
            log["stats"][0]["splits"].append({"date": "2026-05-20", "stat": {"strikeOuts": 30, "plateAppearances": 31}})
        return log
    b = C.build_index(fetch_plus, TEAMS, date(2026, 5, 20), workers=2)
    assert a.rel(TEAMS[3], 2026, "2026-05-20") == b.rel(TEAMS[3], 2026, "2026-05-20")


class _Source(MLBGenericHistorySource):
    def __init__(self, n_starts: int, *, opp: bool = True, index_ok: bool = True):
        super().__init__(opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))
        self.n, self.opp, self.index_ok = n_starts, opp, index_ok

    def player_rows(self, *, player_id, group, target_date):
        return [{"date": date(2026, 4, 1) + timedelta(days=6 * i), "opponent_id": (TEAMS[i % 30] if self.opp else None),
                 "stat": {"gamesStarted": 1, "inningsPitched": "5.1", "strikeOuts": 3 + i % 5, "earnedRuns": 2, "hits": 4, "baseOnBalls": 1}}
                for i in range(self.n)]

    def _team_season(self, team_id, season):
        if not self.index_ok:
            raise RuntimeError("statsapi down")
        return _team_log(team_id, season)

    def _mlb_team_ids(self, season):
        return list(TEAMS)


def _row(src, market, team_id=TEAMS[0]):
    return src.feature_row(game_pk=1, market=market, entity_id="9", target_date=date(2026, 10, 4),
                           away_team_id=TEAMS[0], home_team_id=TEAMS[1], player_id=9, team_id=team_id)


def test_feature_builder_adds_lane_only_for_k_on_normal_path():
    src = _Source(8)
    k = _row(src, "PITCHER_K")
    assert k["joint_feature_version"] == "mlb_pitcher_joint_history_opp_k_v1"
    adj = k["features"]["opp_k_adjustment"]
    assert adj["opponent_team_id"] == TEAMS[1] and len(adj["history_rel"]) == 8 and adj["beta"] == 1.0
    assert "opp_k_adjustment" not in _row(src, "PITCHER_OUTS")["features"]
    assert _row(src, "PITCHER_K", team_id=TEAMS[1])["features"]["opp_k_adjustment"]["opponent_team_id"] == TEAMS[0]


@pytest.mark.parametrize("src,team_id,why", [
    (_Source(8, index_ok=False), TEAMS[0], "index unavailable"),
    (_Source(8, opp=False), TEAMS[0], "opponent missing"),
    (_Source(8), None, "team not resolved"),
    (_Source(8), 999, "team not resolved"),
])
def test_missing_inputs_fall_back_to_unadjusted_price(src, team_id, why):
    row = _row(src, "PITCHER_K", team_id=team_id)
    assert "opp_k_adjustment" not in row["features"] and why in row["opp_k_unadjusted"]
    assert row["joint_feature_version"] == "mlb_pitcher_joint_history_v1"
    out = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 4.5, "features": row["features"]})
    ref = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 4.5,
                                "features": {"history_pool": row["features"]["history_pool"]}})
    assert out["model_p"] == ref["model_p"]
    ev = support_evidence(row, {**out, "american_odds": -110})
    assert why in ev["opp_k_unadjusted"]


def test_index_built_once_per_slate():
    calls = []
    src = _Source(8)
    orig = src._team_season
    src._team_season = lambda t, s: (calls.append((t, s)), orig(t, s))[1]
    _row(src, "PITCHER_K")
    _row(src, "PITCHER_K", team_id=TEAMS[1])
    assert len(calls) == 90  # 30 teams x seasons Y-2..Y, once


def test_support_evidence_and_card_note():
    src = _Source(8)
    row = _row(src, "PITCHER_K")
    half = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 4.5, "features": row["features"]})
    whole = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 5.0, "features": row["features"]})
    ev = support_evidence(row, {**half, "american_odds": -110})
    adj = ev["opp_k_adjustment"]
    assert adj["own_starts"] == 8 and adj["factor"] > 0
    assert half["meta"]["opp_k_adjustment"]["factor"] == pytest.approx(adj["factor"], abs=1e-12)
    assert "integer line" in support_evidence(row, {**whole, "american_odds": -110})["opp_k_unadjusted"]
    payload = {"results": [{"entity_id": "9", "market": "PITCHER_K", "empirical_evidence": ev},
                           {"entity_id": "7", "market": "PITCHER_K", "empirical_evidence": {"opp_k_unadjusted": "opponent K index unavailable (X)"}}]}
    notes = C.opp_k_notes(payload, {"9": "Tarik Skubal"})
    assert notes[0].startswith(f"OPP-K ADJ x{adj['factor']:.2f} Tarik Skubal Pitcher K:") and "LEAN max" in notes[0]
    assert notes[1].startswith("OPP-K UNADJUSTED 7 Pitcher K: opponent K index unavailable")


def test_team_gamelogs_use_history_cache():
    op = MLBHistoryCachedOpener(target_date=date(2026, 10, 4))
    assert op._cache_key("https://statsapi.mlb.com/api/v1/teams/147/stats?stats=gameLog&group=hitting&season=2025&gameType=R")
    assert op._cache_key("https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026") is None
