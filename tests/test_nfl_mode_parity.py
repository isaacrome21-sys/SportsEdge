from __future__ import annotations

import hashlib
import json
import unittest

from sportsedge.sports.nfl.live_runner import run_nfl_live
from sportsedge.sports.nfl.m2 import (
    NFLM2ScoreModel,
    NFL_M2_FEATURE_CONTRACT,
    PRODUCTION_NFL_M2_MODEL_ID,
    _MODEL_FEATURES,
    _REQUIRED_MODEL_FEATURES,
)


CAPTURED = "2026-09-10T23:10:00+00:00"
START = "2026-09-11T00:20:00+00:00"


def _team_features(qb: str) -> dict:
    out = {
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "qb_id": qb,
        "feature_asof_ts": "2026-09-10T23:00:00+00:00",
    }
    for key in _REQUIRED_MODEL_FEATURES:
        out[key] = 0.0
    out["prior_weight"] = 0.5
    return out


def _model() -> NFLM2ScoreModel:
    n = 2 * len(_MODEL_FEATURES)
    return NFLM2ScoreModel(
        model_id=PRODUCTION_NFL_M2_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        feature_names=tuple([f"home_{x}" for x in _MODEL_FEATURES] + [f"away_{x}" for x in _MODEL_FEATURES]),
        feature_means=(0.0,) * n,
        feature_scales=(1.0,) * n,
        margin_coefficients=(7.0,) + (0.0,) * n,
        total_coefficients=(47.0,) + (0.0,) * n,
        train_seasons=(2022, 2023, 2024, 2025),
        ridge_alpha=10.0,
        margin_sigma=13.0,
        total_sigma=10.0,
        residual_correlation=0.0,
        residual_pairs=((0.0, 0.0), (3.0, 4.0), (-4.0, -6.0), (7.0, 3.0), (-9.0, -5.0)),
    )


def _features() -> dict:
    return {
        "schema_version": 3,
        "sport": "nfl",
        "asof_ts": "2026-09-10T23:00:00+00:00",
        "source_manifest_sha256": "a" * 64,
        "games": [{
            "game_id": "2026_01_BET_ALP",
            "game_start_ts": START,
            "home_team": "ALP",
            "away_team": "BET",
            "provider_home_team": "Alpha Aces",
            "provider_away_team": "Beta Bears",
            "home_features": _team_features("qb-home"),
            "away_features": _team_features("qb-away"),
        }],
    }


def _odds() -> list[dict]:
    return [{
        "id": "evt-1",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2026-09-11T00:20:00Z",
        "home_team": "Alpha Aces",
        "away_team": "Beta Bears",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [
                {"key": "h2h", "outcomes": [{"name": "Alpha Aces", "price": -120}, {"name": "Beta Bears", "price": 100}]},
                {"key": "spreads", "outcomes": [{"name": "Alpha Aces", "price": -110, "point": -3.5}, {"name": "Beta Bears", "price": -110, "point": 3.5}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": -105, "point": 46.5}, {"name": "Under", "price": -115, "point": 46.5}]},
            ],
        }],
    }]


def _identity() -> dict:
    return {
        "code_git_sha": "1" * 40,
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "model_artifact_sha256": "b" * 64,
    }


class NFLModeParityTests(unittest.TestCase):
    def test_manual_hybrid_automatic_are_byte_identical_at_shared_core(self):
        features = _features()
        odds = _odds()
        common = dict(model=_model(), captured_at=CAPTURED, identity=_identity())

        manual = run_nfl_live(mode="MANUAL", live_features=features, odds_events=odds, **common)
        hybrid = run_nfl_live(mode="HYBRID", live_features=features, odds_fetcher=lambda: odds, **common)
        automatic = run_nfl_live(mode="AUTOMATIC", feature_builder=lambda: features, odds_fetcher=lambda: odds, **common)

        self.assertEqual(manual, hybrid)
        self.assertEqual(manual, automatic)
        self.assertEqual(
            hashlib.sha256(json.dumps(manual, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            hashlib.sha256(json.dumps(automatic, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        )

        self.assertEqual({row["market"] for row in manual}, {"moneyline", "spread", "total"})
        self.assertTrue(all(row["live_feature_source_manifest_sha256"] == "a" * 64 for row in manual))
        self.assertTrue(all(row["live_feature_asof_ts"] == "2026-09-10T23:00:00+00:00" for row in manual))
        self.assertTrue(all(row["code_git_sha"] == "1" * 40 for row in manual))
        self.assertTrue(all(row["model_artifact_sha256"] == "b" * 64 for row in manual))
        self.assertTrue(all(row["gate_result"] != "OFFICIAL" for row in manual))

    def test_mode_ownership_is_real_and_fail_closed(self):
        common = dict(model=_model(), captured_at=CAPTURED, identity=_identity())
        with self.assertRaisesRegex(ValueError, "NFL_MANUAL_INPUTS_REQUIRED"):
            run_nfl_live(mode="MANUAL", live_features=_features(), **common)
        with self.assertRaisesRegex(ValueError, "NFL_HYBRID_ODDS_FETCHER_REQUIRED"):
            run_nfl_live(mode="HYBRID", live_features=_features(), **common)
        with self.assertRaisesRegex(ValueError, "NFL_AUTOMATIC_FEATURE_BUILDER_REQUIRED"):
            run_nfl_live(mode="AUTOMATIC", odds_fetcher=_odds, **common)

    def test_future_feature_snapshot_fails_closed_in_every_mode(self):
        future = _features()
        future["asof_ts"] = "2026-09-10T23:20:00+00:00"
        common = dict(model=_model(), captured_at=CAPTURED, identity=_identity())
        calls = [
            lambda: run_nfl_live(mode="MANUAL", live_features=future, odds_events=_odds(), **common),
            lambda: run_nfl_live(mode="HYBRID", live_features=future, odds_fetcher=_odds, **common),
            lambda: run_nfl_live(mode="AUTOMATIC", feature_builder=lambda: future, odds_fetcher=_odds, **common),
        ]
        for call in calls:
            with self.subTest(call=call), self.assertRaisesRegex(ValueError, "NFL_LIVE_FEATURE_FROM_FUTURE"):
                call()


if __name__ == "__main__":
    unittest.main()
