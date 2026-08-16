import unittest
from datetime import date, timedelta

from sportsedge.v7_candidate import load_candidate, score_candidate
from sportsedge.v7_feature_bundle import (
    V7_COMBINED_FEATURE_CONTRACT_SHA256,
    build_v7_feature_payload,
)
from sportsedge.v7_training import train_chronological_candidate


class V7StaticContractTrainingTests(unittest.TestCase):
    def _payload(self, *, as_of: str, starter_event: str, starter_pitches: int):
        forecast_day = as_of[:10]
        return build_v7_feature_payload(
            as_of=as_of,
            starter_rows=[{"event_time": starter_event, "pitches": starter_pitches, "is_start": True}],
            bullpen_rows=[],
            statcast_rows=[],
            platoon={
                "batter_hand": "R", "pitcher_hand": "L",
                "batter_xwoba_vs_hand": 0.330,
                "pitcher_xwoba_allowed_vs_hand": 0.315,
            },
            park={"venue_id": 1, "run_factor": 1.01, "hr_factor_lhb": 0.99, "hr_factor_rhb": 1.02},
            weather={
                "issued_at": f"{forecast_day}T12:00:00Z",
                "valid_at": f"{forecast_day}T20:00:00Z",
                "temperature_f": 80, "humidity_pct": 50, "pressure_hpa": 1012,
                "wind_mph": 8, "wind_out_to_center_mph": 3,
                "precip_probability": 0.1, "roof_closed": False,
            },
            travel={
                "previous_lat": 41.88, "previous_lon": -87.63,
                "current_lat": 41.95, "current_lon": -87.66,
                "timezone_shift_hours": 0, "days_rest": 1,
                "consecutive_game_days": 3, "doubleheader": False,
            },
            umpire=None,
            catcher=None,
        )

    def test_static_contract_same_across_games_payload_hash_changes(self):
        a = self._payload(
            as_of="2026-08-16T17:00:00Z",
            starter_event="2026-08-10T17:00:00Z",
            starter_pitches=90,
        )
        b = self._payload(
            as_of="2026-08-16T18:00:00Z",
            starter_event="2026-08-11T18:00:00Z",
            starter_pitches=101,
        )
        self.assertEqual(a["feature_contract_sha256"], V7_COMBINED_FEATURE_CONTRACT_SHA256)
        self.assertEqual(a["feature_contract_sha256"], b["feature_contract_sha256"])
        self.assertNotEqual(a["feature_payload_sha256"], b["feature_payload_sha256"])

    def test_chronological_training_freezes_candidate_on_static_contract(self):
        feature_paths = ("baseball.starter.days_rest", "context.park.run_factor")
        rows = []
        start = date(2026, 6, 1)
        for i in range(16):
            game_day = start + timedelta(days=i)
            as_of = f"{game_day.isoformat()}T17:00:00Z"
            starter_day = game_day - timedelta(days=4 + (i % 3))
            payload = self._payload(
                as_of=as_of,
                starter_event=f"{starter_day.isoformat()}T17:00:00Z",
                starter_pitches=85 + i,
            )
            rows.append({
                "game_date": game_day.isoformat(),
                "feature_payload": payload,
                "outcome": i % 2,
            })

        artifact, report = train_chronological_candidate(
            rows,
            model_name="v7_unit_test",
            train_end="2026-06-10",
            calibration_start="2026-06-11",
            calibration_end="2026-06-14",
            holdout_start="2026-06-15",
            feature_paths=feature_paths,
            iterations=200,
            learning_rate=0.05,
        )
        candidate = load_candidate(artifact)
        self.assertEqual(candidate.feature_contract_sha256, V7_COMBINED_FEATURE_CONTRACT_SHA256)
        self.assertLess(report["fit_max_date"], report["holdout_start"])
        p = score_candidate(candidate, rows[-1]["feature_payload"])
        self.assertGreater(p, 0.0)
        self.assertLess(p, 1.0)
        self.assertFalse(report["sportsbook_data_used"])


if __name__ == "__main__":
    unittest.main()
