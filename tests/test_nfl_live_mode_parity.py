import unittest
from unittest.mock import patch

import sportsedge.sports.nfl.live_runner as live_runner
from sportsedge.sports.nfl.m2 import (
    NFLM2ScoreModel,
    NFL_M2_FEATURE_CONTRACT,
    PRODUCTION_NFL_M2_MODEL_ID,
)

CAPTURED_AT = "2026-09-10T23:10:00+00:00"
GAME_START = "2026-09-11T00:20:00+00:00"
SOURCE_SHA = "b" * 64

_REQUIRED = (
    "adj_off_epa", "adj_def_epa", "pass_epa", "rush_epa", "pressure_for",
    "pressure_allowed", "success_rate", "explosive_rate", "rest_diff_days",
    "travel_miles", "timezone_crossings", "short_week", "bye_week", "wind_mph",
    "roof_closed", "qb_adjustment", "prior_efficiency", "prior_weight",
)
_OPTIONAL = (
    "opp_wr_target_share_oe_allowed", "opp_te_target_share_oe_allowed",
    "opp_rb_target_share_oe_allowed", "opp_wr_target_share_oe_weighted",
    "opp_te_target_share_oe_weighted", "opp_rb_target_share_oe_weighted",
    "defensive_playcaller_continuity_weight", "defensive_playcaller_changed",
    "off_wr_target_share", "off_te_target_share", "off_rb_target_share",
    "wr_usage_x_opp_target_oe", "te_usage_x_opp_target_oe", "rb_usage_x_opp_target_oe",
    "positional_target_matchup_pressure",
)


def side_features(qb_id):
    out = {name: 0.0 for name in _REQUIRED}
    out["prior_weight"] = 0.5
    out.update({
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "qb_id": qb_id,
        "feature_asof_ts": "2026-09-10T22:55:00+00:00",
    })
    return out


def game_row():
    return {
        "game_id": "2026_01_BET_ALP",
        "game_start_ts": GAME_START,
        "home_team": "ALP",
        "away_team": "BET",
        "provider_home_team": "Alpha Aces",
        "provider_away_team": "Beta Bears",
        "home_features": side_features("QB-HOME"),
        "away_features": side_features("QB-AWAY"),
    }


def live_features():
    return {
        "sport": "nfl",
        "source_manifest_sha256": SOURCE_SHA,
        "asof_ts": "2026-09-10T22:55:00+00:00",
        "games": [game_row()],
    }


def odds_events():
    return [{
        "id": "evt-1",
        "sport_key": "americanfootball_nfl",
        "commence_time": GAME_START,
        "home_team": "Alpha Aces",
        "away_team": "Beta Bears",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Alpha Aces", "price": -120},
                    {"name": "Beta Bears", "price": 100},
                ]},
                {"key": "spreads", "outcomes": [
                    {"name": "Alpha Aces", "price": -110, "point": -3.0},
                    {"name": "Beta Bears", "price": -110, "point": 3.0},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -105, "point": 45.5},
                    {"name": "Under", "price": -115, "point": 45.5},
                ]},
            ],
        }],
    }]


def model():
    feature_count = 2 * (len(_REQUIRED) + len(_OPTIONAL))
    # Intercepts produce a market-blind 3-point home margin / 45-point total.
    return NFLM2ScoreModel(
        model_id=PRODUCTION_NFL_M2_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        feature_names=tuple(f"f{i}" for i in range(feature_count)),
        feature_means=(0.0,) * feature_count,
        feature_scales=(1.0,) * feature_count,
        margin_coefficients=(3.0,) + (0.0,) * feature_count,
        total_coefficients=(45.0,) + (0.0,) * feature_count,
        train_seasons=(2024, 2025),
        ridge_alpha=10.0,
        margin_sigma=7.0,
        total_sigma=8.0,
        residual_correlation=0.0,
        residual_pairs=((-7.0, -6.0), (0.0, 0.0), (7.0, 6.0), (3.0, -4.0), (-3.0, 4.0)),
    )


def identity():
    return {
        "code_git_sha": "1" * 40,
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "model_artifact_sha256": "a" * 64,
    }


def canonical_call(mocked):
    kwargs = mocked.call_args.kwargs
    return {
        "model": kwargs["model"],
        "live_features": kwargs["live_features"],
        "odds_events": kwargs["odds_events"],
        "captured_at": kwargs["captured_at"],
        "identity": kwargs["identity"],
    }


class NFLLiveModeParityTests(unittest.TestCase):
    def test_manual_hybrid_automatic_are_byte_identical_after_ingress_resolution(self):
        m = model()
        features = live_features()
        odds = odds_events()
        ids = identity()

        with patch.object(live_runner, "run_canonical_nfl_live", wraps=live_runner.run_canonical_nfl_live) as core:
            manual = live_runner.run_nfl_live(
                mode="MANUAL", model=m, captured_at=CAPTURED_AT, identity=ids,
                live_features=features, odds_events=odds,
            )
            manual_call = canonical_call(core)

        with patch.object(live_runner, "run_canonical_nfl_live", wraps=live_runner.run_canonical_nfl_live) as core:
            hybrid = live_runner.run_nfl_live(
                mode="HYBRID", model=m, captured_at=CAPTURED_AT, identity=ids,
                live_features=features, odds_fetcher=lambda: odds,
            )
            hybrid_call = canonical_call(core)

        feature_calls = []
        odds_calls = []
        with patch.object(live_runner, "run_canonical_nfl_live", wraps=live_runner.run_canonical_nfl_live) as core:
            automatic = live_runner.run_nfl_live(
                mode="AUTOMATIC", model=m, captured_at=CAPTURED_AT, identity=ids,
                feature_builder=lambda: feature_calls.append("called") or features,
                odds_fetcher=lambda: odds_calls.append("called") or odds,
            )
            automatic_call = canonical_call(core)

        self.assertEqual(feature_calls, ["called"])
        self.assertEqual(odds_calls, ["called"])
        self.assertEqual(manual_call, hybrid_call)
        self.assertEqual(hybrid_call, automatic_call)
        self.assertEqual(manual, hybrid)
        self.assertEqual(hybrid, automatic)
        self.assertEqual(len(manual), 3)

        economic_fields = (
            "game_id", "market", "side", "book", "line_at_decision", "price_at_decision",
            "model_prob", "model_push_prob", "model_loss_prob", "novig_prob", "ev",
            "kelly_frac", "stake_units", "gate_result", "selection_contract",
            "provider_event_id", "provider_event_snapshot_sha256", "provider_home_team",
            "provider_away_team", "provider_side_name", "code_git_sha", "model_id",
            "feature_contract", "model_artifact_sha256", "live_feature_source_manifest_sha256",
            "live_feature_asof_ts", "decision_ts", "game_start_ts",
        )
        for row in manual:
            self.assertEqual(row["live_feature_source_manifest_sha256"], SOURCE_SHA)
            self.assertEqual(row["model_id"], PRODUCTION_NFL_M2_MODEL_ID)
            self.assertTrue(all(field in row for field in economic_fields))
            self.assertNotIn("mode", row)

    def test_each_mode_rejects_missing_mode_owned_ingress(self):
        common = dict(model=model(), captured_at=CAPTURED_AT, identity=identity())
        with self.assertRaisesRegex(ValueError, "NFL_MANUAL_INPUTS_REQUIRED"):
            live_runner.run_nfl_live(mode="MANUAL", live_features=live_features(), **common)
        with self.assertRaisesRegex(ValueError, "NFL_HYBRID_ODDS_FETCHER_REQUIRED"):
            live_runner.run_nfl_live(mode="HYBRID", live_features=live_features(), **common)
        with self.assertRaisesRegex(ValueError, "NFL_AUTOMATIC_FEATURE_BUILDER_REQUIRED"):
            live_runner.run_nfl_live(mode="AUTOMATIC", odds_fetcher=odds_events, **common)


if __name__ == "__main__":
    unittest.main()
