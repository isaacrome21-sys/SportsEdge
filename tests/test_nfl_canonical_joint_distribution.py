"""RED: the canonical NFL path must be able to emit a joint score
distribution from the Lane A (market-blind) means, so the wired team-total
derivative pricer stops starving. Default OFF; research-only; unvalidated."""
import math

import pytest

from sportsedge.nfl_canonical_joint_distribution import (
    ENABLED_BY_DEFAULT,
    CanonicalJointDistributionError,
    attach_canonical_distribution,
    canonical_joint_score_distribution,
)


def _game(h=24.0, a=20.0, sport="NFL", lane="lane_a_independent"):
    return {"sport": sport, "away": "Buffalo Bills", "home": "Kansas City Chiefs",
            "pricing_lanes": {lane: {"home_mean": h, "away_mean": a}}}


def test_default_off():
    assert ENABLED_BY_DEFAULT is False


def test_paths_are_integer_nonnegative_and_deterministic():
    d1 = canonical_joint_score_distribution(_game(), n_sims=4000)
    d2 = canonical_joint_score_distribution(_game(), n_sims=4000)
    assert d1["rows"] == d2["rows"] and len(d1["rows"]) == 4000
    for r in d1["rows"][:200]:
        assert isinstance(r["home_score"], int) and r["home_score"] >= 0
        assert isinstance(r["away_score"], int) and r["away_score"] >= 0


def test_means_track_lane_a_means():
    d = canonical_joint_score_distribution(_game(27.0, 17.0), n_sims=20000)
    hm = sum(r["home_score"] for r in d["rows"]) / len(d["rows"])
    am = sum(r["away_score"] for r in d["rows"]) / len(d["rows"])
    assert abs(hm - 27.0) < 1.0 and abs(am - 17.0) < 1.0


def test_meta_is_honest():
    m = canonical_joint_score_distribution(_game(), n_sims=1000)["meta"]
    assert m["source"] == "LANE_A_MEANS_X_DISCRETE_V2_FROZEN_SHAPE"
    assert m["validated"] is False and m["research_only"] is True
    assert m["market_inputs"] is False
    assert len(m["shape_freeze_sha256"]) == 64
    assert m["n_sims"] == 1000 and isinstance(m["seed"], int)


@pytest.mark.parametrize("game", [
    _game(sport="MLB"),
    _game(lane="lane_b_anchored"),
    {"sport": "NFL", "pricing_lanes": {}},
    _game(h=float("nan")),
    _game(h=-3.0),
])
def test_refusals(game):
    with pytest.raises(CanonicalJointDistributionError):
        canonical_joint_score_distribution(game, n_sims=100)


def test_attach_does_not_mutate_and_adds_key():
    g = _game()
    out = attach_canonical_distribution(g, n_sims=500)
    assert "joint_score_distribution" not in g
    assert len(out["joint_score_distribution"]) == 500
    assert out["joint_score_distribution_meta"]["validated"] is False


def test_attach_keeps_existing_distribution():
    g = _game(); g["score_paths"] = [{"home_score": 1, "away_score": 0}]
    assert attach_canonical_distribution(g) is g


def test_team_total_pricer_prices_from_canonical_distribution():
    from sportsedge.nfl_phone_derivative_pricing import (
        extract_distribution, fixture_key, phone_nfl_derivative_rows)
    g = attach_canonical_distribution(_game(), n_sims=5000)
    dist = extract_distribution(g)
    rows = [{"market": "TEAM_TOTAL", "side": "HOME", "line": 23.5,
             "away": g["away"], "home": g["home"]},
            {"market": "TEAM_TOTAL", "side": "AWAY", "line": 20.5,
             "away": g["away"], "home": g["home"]}]
    out, _ = phone_nfl_derivative_rows(rows, distributions={fixture_key(g["away"], g["home"]): dist})
    assert [o["status"] for o in out] == ["PRICED_RESEARCH", "PRICED_RESEARCH"]
    assert all(o["research_only"] and not o["staking_authority"] for o in out)


def test_run_it_wiring_respects_flag(monkeypatch):
    import artifacts.run_it_full as rif
    import sportsedge.nfl_canonical_joint_distribution as m
    g = _game()
    assert rif._nfl_canonical_distribution(g) is None  # default OFF
    monkeypatch.setattr(m, "ENABLED_BY_DEFAULT", True)
    dist = rif._nfl_canonical_distribution(g)
    assert dist and len(dist) == m.DEFAULT_N_SIMS
    assert rif._nfl_canonical_distribution(_game(lane="lane_b_anchored")) is None
