import unittest

from sportsedge.v7_environment_context import (
    V7ContextError,
    build_v7_environment_context,
    catcher_context,
    haversine_km,
    umpire_context,
    weather_context,
)

AS_OF = "2026-08-16T18:00:00Z"


class V7EnvironmentContextTests(unittest.TestCase):
    def test_weather_must_be_issued_before_asof(self):
        row = {
            "issued_at":"2026-08-16T18:01:00Z", "valid_at":"2026-08-16T20:00:00Z",
            "temperature_f":80, "humidity_pct":50, "pressure_hpa":1012,
            "wind_mph":10, "wind_out_to_center_mph":5, "precip_probability":.1,
        }
        with self.assertRaises(V7ContextError):
            weather_context(row, as_of=AS_OF)

    def test_weather_wind_component_cannot_exceed_speed(self):
        row = {
            "issued_at":"2026-08-16T17:00:00Z", "valid_at":"2026-08-16T20:00:00Z",
            "temperature_f":80, "humidity_pct":50, "pressure_hpa":1012,
            "wind_mph":5, "wind_out_to_center_mph":10, "precip_probability":.1,
        }
        with self.assertRaises(V7ContextError):
            weather_context(row, as_of=AS_OF)

    def test_unknown_umpire_and_catcher_are_explicit_neutral_not_invented(self):
        self.assertEqual(umpire_context(None).assignment_known, 0.0)
        self.assertEqual(catcher_context(None).catcher_known, 0.0)
        self.assertEqual(umpire_context(None).bb_rate_delta, 0.0)
        self.assertEqual(catcher_context(None).strike_rate_delta, 0.0)

    def test_haversine_is_symmetric(self):
        a = haversine_km(41.9484, -87.6553, 34.0739, -118.2400)
        b = haversine_km(34.0739, -118.2400, 41.9484, -87.6553)
        self.assertAlmostEqual(a, b, places=9)
        self.assertGreater(a, 2500)

    def test_full_context_is_deterministic(self):
        kwargs = dict(
            as_of=AS_OF,
            park={"venue_id":17,"run_factor":1.03,"hr_factor_lhb":1.08,"hr_factor_rhb":1.05},
            weather={
                "issued_at":"2026-08-16T17:00:00Z","valid_at":"2026-08-16T20:00:00Z",
                "temperature_f":82,"humidity_pct":55,"pressure_hpa":1010,
                "wind_mph":12,"wind_out_to_center_mph":8,"precip_probability":.05,"roof_closed":False,
            },
            travel={
                "previous_lat":39.7561,"previous_lon":-104.9942,"current_lat":41.9484,"current_lon":-87.6553,
                "timezone_shift_hours":1,"days_rest":0,"consecutive_game_days":6,"doubleheader":False,
            },
            umpire={"prior_pitches":5000,"called_strike_delta":.01,"bb_rate_delta":-.002,"run_rate_delta":.05},
            catcher={"prior_called_pitches":3000,"framing_runs_per_1000":1.2,"strike_rate_delta":.006},
        )
        a = build_v7_environment_context(**kwargs)
        b = build_v7_environment_context(**kwargs)
        self.assertEqual(a, b)
        self.assertEqual(len(a["feature_contract_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
