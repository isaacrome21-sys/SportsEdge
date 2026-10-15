"""Full-game Total Runs 3-Way distribution tests. Offline fixtures only.

Proves sportsedge.game_total_distribution: the joint full-game score
state builds from strictly-prior final-score arrays, the 3-way
read-outs (OVER / EXACTLY / UNDER at an integer line) partition the
posterior settlement mass with the EXACTLY cell carried as its own
probability and push mass identically zero, the league-prior (m30)
path is wired, and malformed inputs fail closed. Also covers the
feature source (strictly-prior final scores via the F5 source's
verified reduction) and the shared engine session.
"""
from __future__ import annotations

import json

import pytest

from sportsedge.game_total_distribution import (
    GameTotalDistributionError,
    build_game_total_distribution,
    distribution_version,
    read_game_total_probability,
    readout_version,
)


def _features(n=20):
    return {
        "away_game_runs_for": [(i % 7) + 1 for i in range(n)],
        "away_game_runs_against": [(i + 1) % 6 + 1 for i in range(n)],
        "home_game_runs_for": [(i + 2) % 7 + 1 for i in range(n)],
        "home_game_runs_against": [i % 6 + 1 for i in range(n)],
    }


def _league_features(n=20):
    feats = _features(n=n)
    feats["league_game_pmf"] = {
        "0": 0.03, "1": 0.08, "2": 0.13, "3": 0.16, "4": 0.17, "5": 0.14,
        "6": 0.11, "7": 0.07, "8": 0.05, "9": 0.03, "10": 0.02, "11": 0.01,
    }
    feats["league_prior_halves"] = 4000
    feats["league_prior_strength"] = 30
    return feats


def test_build_conserves_and_versions():
    dist = build_game_total_distribution(_features())
    assert dist.distribution_version == distribution_version(league_prior_strength=0)
    assert "candidate" in dist.distribution_version
    assert abs(sum(dist.joint_score_pmf.values()) - 1.0) < 1e-12
    assert len(dist.distribution_sha256) == 64
    assert dist.away_history_games == 20
    assert dist.home_history_games == 20


def test_three_way_readouts_partition_the_posterior():
    dist = build_game_total_distribution(_features())
    readouts = {
        side: read_game_total_probability(
            dist, market="GAME_TOTAL_3_WAY", line=8, side=side)
        for side in ("OVER", "EXACTLY", "UNDER")
    }
    total = sum(r.probability for r in readouts.values())
    assert total == pytest.approx(1.0, abs=1e-9)
    for readout in readouts.values():
        # A 3-way selection never pushes, and every side's readout
        # reports the same EXACTLY-cell probability.
        assert readout.push_probability == 0.0
        assert readout.exactly_probability == pytest.approx(
            readouts["EXACTLY"].probability, abs=1e-12)
        assert readout.readout_version == readout_version()
        assert len(readout.readout_sha256) == 64
    # The fixture histories land on a total of 8 with real frequency.
    assert readouts["EXACTLY"].probability > 0.05


def test_exactly_probability_matches_raw_cell_direction():
    # All history totals are exactly 8: the EXACTLY cell must dominate
    # at line 8 and vanish (up to Jeffreys stabilization) at line 9.
    feats = {
        "away_game_runs_for": [4] * 12, "away_game_runs_against": [4] * 12,
        "home_game_runs_for": [4] * 12, "home_game_runs_against": [4] * 12,
    }
    dist = build_game_total_distribution(feats)
    at8 = read_game_total_probability(dist, market="GAME_TOTAL_3_WAY", line=8, side="EXACTLY")
    assert at8.probability > 0.8
    at9 = read_game_total_probability(dist, market="GAME_TOTAL_3_WAY", line=9, side="EXACTLY")
    assert at9.probability < 0.1
    under9 = read_game_total_probability(dist, market="GAME_TOTAL_3_WAY", line=9, side="UNDER")
    assert under9.probability > 0.8


def test_league_prior_path_builds_with_production_version():
    dist = build_game_total_distribution(
        _league_features(), league_prior_strength=30)
    assert dist.distribution_version == distribution_version()
    assert "m30" in dist.distribution_version
    readout = read_game_total_probability(
        dist, market="GAME_TOTAL_3_WAY", line=9, side="OVER")
    assert 0.0 < readout.probability < 1.0


def test_deterministic_distribution_identity():
    first = build_game_total_distribution(_league_features(), league_prior_strength=30)
    second = build_game_total_distribution(_league_features(), league_prior_strength=30)
    assert first.distribution_sha256 == second.distribution_sha256
    assert first.joint_score_pmf == second.joint_score_pmf


@pytest.mark.parametrize("line", [8.5, -1, "x", None, True])
def test_non_integer_or_invalid_lines_refused(line):
    dist = build_game_total_distribution(_features())
    with pytest.raises(GameTotalDistributionError):
        read_game_total_probability(
            dist, market="GAME_TOTAL_3_WAY", line=line, side="OVER")


def test_bad_side_and_wrong_market_refused():
    dist = build_game_total_distribution(_features())
    with pytest.raises(GameTotalDistributionError):
        read_game_total_probability(
            dist, market="GAME_TOTAL_3_WAY", line=8, side="HOME")
    with pytest.raises(GameTotalDistributionError):
        read_game_total_probability(
            dist, market="TOTALS", line=8, side="OVER")


def test_insufficient_history_refused():
    feats = _features(n=9)
    with pytest.raises(GameTotalDistributionError):
        build_game_total_distribution(feats)


def test_misaligned_arrays_refused():
    feats = _features()
    feats["away_game_runs_against"] = feats["away_game_runs_against"][:-1]
    with pytest.raises(GameTotalDistributionError):
        build_game_total_distribution(feats)


def test_bad_league_prior_refused():
    feats = _league_features()
    feats["league_game_pmf"] = {"0": 0.5}  # does not conserve
    with pytest.raises(GameTotalDistributionError):
        build_game_total_distribution(feats, league_prior_strength=30)
    feats = _league_features()
    feats["league_prior_halves"] = 100  # below MIN_LEAGUE_HALVES
    with pytest.raises(GameTotalDistributionError):
        build_game_total_distribution(feats, league_prior_strength=30)
    with pytest.raises(GameTotalDistributionError):
        build_game_total_distribution(_features(), league_prior_strength=7)


# ------------------------------------------------------- engine session

def test_engine_session_readouts_and_cache():
    from sportsedge.shared_game_total_engine import (
        SharedGameTotalEngineError, build_shared_game_total_engine_session)
    session = build_shared_game_total_engine_session()
    model_input = {
        "game_id": "777002", "market": "GAME_TOTAL_3_WAY",
        "entity_id": "777002", "line": 8, "side": "EXACTLY",
        "features": _league_features(), "feature_source_hash": "abc123",
    }
    out = session(model_input)
    assert out["model_p"] == out["exactly_p"] > 0.0
    assert out["push_p"] == 0.0
    assert len(out["distribution_sha256"]) == 64
    assert len(out["readout_sha256"]) == 64
    assert out["mc_paths"] == 0
    again = session(dict(model_input, side="OVER"))
    assert again["distribution_sha256"] == out["distribution_sha256"]
    assert again["model_input_hash"] == out["model_input_hash"]
    with pytest.raises(SharedGameTotalEngineError):
        session(dict(model_input, market="F3_TOTALS"))
    with pytest.raises(SharedGameTotalEngineError):
        session(dict(model_input, feature_source_hash=""))


# ------------------------------------------------------------ features

class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _history_payload(games=120):
    out = []
    for i in range(games):
        day = 1 + (i % 13)
        out.append({
            "gamePk": 9000 + i,
            "gameDate": f"2026-09-{day:02d}T23:10:00Z",
            "officialDate": f"2026-09-{day:02d}",
            "status": {"abstractGameState": "Final"},
            "teams": {
                "away": {"team": {"id": 101}, "score": 3 + (i % 5)},
                "home": {"team": {"id": 202}, "score": 2 + (i % 4)},
            },
            "linescore": {"innings": [
                {"num": n, "away": {"runs": 0}, "home": {"runs": 0}}
                for n in range(1, 10)]},
        })
    return {"dates": [{"date": "2026-09-13", "games": out}]}


def test_feature_source_assembles_strictly_prior_finals():
    from datetime import date, datetime, timezone
    from sportsedge.mlb_game_total_features import MLBGameTotalHistorySource
    source = MLBGameTotalHistorySource(
        opener=lambda request, timeout=0: _Response(_history_payload()),
        retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc))
    features = source.game_matchup_features(
        away_team_id=101, home_team_id=202, target_date=date(2026, 9, 14))
    assert features["feature_version"] == "mlb_game_total_actual_finals_v1"
    assert features["away_history_games"] == 30  # HISTORY_WINDOW_GAMES
    assert features["home_history_games"] == 30
    payload = features["features"]
    assert set(payload["away_game_runs_for"]) <= {3, 4, 5, 6, 7}
    assert set(payload["home_game_runs_for"]) <= {2, 3, 4, 5}
    assert payload["league_prior_halves"] == 240
    assert abs(sum(payload["league_game_pmf"].values()) - 1.0) < 1e-9
    assert len(features["feature_source_hash"]) == 64
    # The assembled features feed the production (m30) distribution.
    dist = build_game_total_distribution(payload, league_prior_strength=30)
    assert abs(sum(dist.joint_score_pmf.values()) - 1.0) < 1e-12


def test_feature_source_fails_closed_without_history():
    from datetime import date, datetime, timezone
    from sportsedge.mlb_f5_features import MLBF5FeatureError
    from sportsedge.mlb_game_total_features import MLBGameTotalHistorySource
    source = MLBGameTotalHistorySource(
        opener=lambda request, timeout=0: _Response({"dates": []}),
        retrieved_at=datetime(2026, 9, 14, tzinfo=timezone.utc))
    with pytest.raises(MLBF5FeatureError):
        source.game_matchup_features(
            away_team_id=101, home_team_id=202,
            target_date=date(2026, 9, 14))
