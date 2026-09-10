import unittest

from sportsedge.sports.nfl.m2_history_policy import environment_exclusion_reasons


class NFLM2HistoryEnvironmentPolicyTests(unittest.TestCase):
    def _row(self, *, roof="outdoors", wind="8", wind_mph=None):
        row = {
            "home_rest": 7,
            "away_rest": 7,
            "roof": roof,
            "wind": wind,
        }
        if wind_mph is not None:
            row["wind_mph"] = wind_mph
        return row

    def test_closed_roof_blank_wind_is_structural_zero(self):
        row = self._row(roof="closed", wind="")
        self.assertNotIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))

    def test_dome_missing_wind_is_structural_zero(self):
        row = self._row(roof="dome", wind=None)
        self.assertNotIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))

    def test_open_roof_blank_wind_remains_invalid(self):
        row = self._row(roof="open", wind="")
        self.assertIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))

    def test_outdoor_blank_wind_remains_invalid(self):
        row = self._row(roof="outdoors", wind="")
        self.assertIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))

    def test_closed_roof_negative_supplied_wind_remains_invalid(self):
        row = self._row(roof="closed", wind="-1")
        self.assertIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))

    def test_closed_roof_malformed_supplied_wind_remains_invalid(self):
        row = self._row(roof="closed", wind="bad")
        self.assertIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))

    def test_closed_roof_boolean_supplied_wind_remains_invalid(self):
        row = self._row(roof="closed", wind=True)
        self.assertIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))

    def test_supplied_wind_mph_alias_is_not_hidden_by_valid_fallback(self):
        row = self._row(roof="closed", wind="8", wind_mph="bad")
        self.assertIn("NFL_WIND_INVALID", environment_exclusion_reasons(row))


if __name__ == "__main__":
    unittest.main()
