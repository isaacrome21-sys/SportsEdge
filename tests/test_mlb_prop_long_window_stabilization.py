import pytest

from sportsedge.hitter_joint_engine import price_hitter_market
from sportsedge.pitcher_joint_engine import price_pitcher_market


def _hitter_row(*, hr: int) -> dict:
    hits = 1
    singles = hits - hr
    return {
        "plate_appearances": 4,
        "hits": hits,
        "singles": singles,
        "doubles": 0,
        "triples": 0,
        "home_runs": hr,
        "total_bases": singles + 4 * hr,
        "rbi": hr,
        "runs": hr,
        "stolen_bases": 0,
        "walks": 0,
        "strikeouts": 1,
        "extra_base_hits": hr,
    }


def _pitcher_row(*, k: int = 6, er: int = 1) -> dict:
    return {
        "strikeouts": k,
        "outs": 18,
        "earned_runs": er,
        "hits_allowed": 5,
        "walks_allowed": 2,
    }


def test_hitter_long_window_prior_pulls_recent_endpoint_without_overriding_recent_sample():
    recent = [_hitter_row(hr=1) for _ in range(10)]
    older = [_hitter_row(hr=0) for _ in range(10)]
    base = {
        "game_id": "g",
        "market": "HOME_RUNS",
        "entity_id": "b",
        "line": 0.5,
        "side": "OVER",
        "feature_source_hash": "a" * 64,
    }

    recent_only = price_hitter_market({**base, "features": {"history_pool": recent}})
    stabilized = price_hitter_market({
        **base,
        "features": {"history_pool": recent, "prior_pool": older},
    })

    assert recent_only["model_p"] > 0.95
    assert stabilized["model_p"] == pytest.approx(0.5)
    prior = stabilized["meta"]["long_window_prior"]
    assert prior["history_games"] == 10
    assert prior["strength"] == pytest.approx(
        stabilized["meta"]["effective_history_games"]
    )


def test_pitcher_long_window_prior_stabilizes_uncontextualized_er_tail():
    recent = [_pitcher_row(er=0) for _ in range(10)]
    older = [_pitcher_row(er=3) for _ in range(10)]
    base = {
        "game_id": "g",
        "market": "PITCHER_ER",
        "entity_id": "p",
        "line": 1.5,
        "side": "OVER",
        "feature_source_hash": "b" * 64,
    }

    recent_only = price_pitcher_market({**base, "features": {"history_pool": recent}})
    stabilized = price_pitcher_market({
        **base,
        "features": {"history_pool": recent, "prior_pool": older},
    })

    assert recent_only["model_p"] < 0.05
    assert stabilized["model_p"] == pytest.approx(0.5)
    assert stabilized["meta"]["long_window_prior"]["strength"] == pytest.approx(10.0)


def test_validated_pitcher_k_context_path_ignores_long_window_prior():
    recent = [_pitcher_row(k=6) for _ in range(5)]
    older = [_pitcher_row(k=0) for _ in range(20)]
    adjustment = {
        "market": "PITCHER_K",
        "beta": 1.0,
        "target_rel": 1.0,
        "history_rel": [1.0] * 5,
        "opponent_team_id": 20,
        "validated_in": "#1509",
    }
    base = {
        "game_id": "g",
        "market": "PITCHER_K",
        "entity_id": "p",
        "line": 5.5,
        "side": "OVER",
        "feature_source_hash": "c" * 64,
    }

    plain = price_pitcher_market({
        **base,
        "features": {"history_pool": recent, "opp_k_adjustment": adjustment},
    })
    with_prior = price_pitcher_market({
        **base,
        "features": {
            "history_pool": recent,
            "prior_pool": older,
            "opp_k_adjustment": adjustment,
        },
    })

    assert with_prior["model_p"] == pytest.approx(plain["model_p"], abs=1e-12, rel=0)
    assert "long_window_prior" not in with_prior["meta"]


def test_hitter_integer_line_mass_still_conserves_with_prior():
    recent = [_hitter_row(hr=1) for _ in range(10)]
    older = [_hitter_row(hr=0) for _ in range(10)]
    rows = []
    for side in ("OVER", "UNDER"):
        rows.append(price_hitter_market({
            "game_id": "g",
            "market": "HOME_RUNS",
            "entity_id": "b",
            "line": 1.0,
            "side": side,
            "feature_source_hash": "d" * 64,
            "features": {"history_pool": recent, "prior_pool": older},
        }))
    assert rows[0]["model_p"] + rows[1]["model_p"] + rows[0]["push_p"] == pytest.approx(1.0)
