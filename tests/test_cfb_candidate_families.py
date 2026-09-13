import unittest

from sportsedge.sports.cfb.candidate_families import (
    CFBCandidateFamilyError,
    FAMILY_EQUAL_WEIGHT_HARD_SWITCH,
    IMPLEMENTED_FAMILIES,
    TEAM_METRIC_KEYS,
    materialize_candidate_row,
)


def metrics(*, season, through_week, sample_source):
    row = {key: 0.1 for key in TEAM_METRIC_KEYS}
    row.update(season=season, through_week=through_week, sample_source=sample_source)
    return row


class TestCFBCandidateFamilies(unittest.TestCase):
    def base_row(self, *, season=2025, week=2):
        return {
            "season": season,
            "week": week,
            "neutral_site": False,
            "home_metrics": metrics(season=season, through_week=week - 1, sample_source="CURRENT_SEASON_PRIOR_WEEKS"),
            "away_metrics": metrics(season=season, through_week=week - 1, sample_source="CURRENT_SEASON_PRIOR_WEEKS"),
            "weather": {"game_indoor": True},
            "home_score": 31,
            "away_score": 24,
        }

    def test_only_baseline_family_is_implemented(self):
        self.assertEqual(IMPLEMENTED_FAMILIES, {FAMILY_EQUAL_WEIGHT_HARD_SWITCH})

    def test_week2_plus_requires_exact_prior_week_current_season_metrics(self):
        row = self.base_row(week=4)
        self.assertEqual(materialize_candidate_row(FAMILY_EQUAL_WEIGHT_HARD_SWITCH, row), row)
        row["home_metrics"]["through_week"] = 2
        with self.assertRaisesRegex(CFBCandidateFamilyError, "CURRENT_SEASON_SWITCH_INVALID"):
            materialize_candidate_row(FAMILY_EQUAL_WEIGHT_HARD_SWITCH, row)

    def test_week1_requires_immediately_prior_season_fallback(self):
        row = self.base_row(season=2025, week=1)
        row["home_metrics"] = metrics(season=2024, through_week=99, sample_source="PRIOR_SEASON_FALLBACK")
        row["away_metrics"] = metrics(season=2024, through_week=99, sample_source="PRIOR_SEASON_FALLBACK")
        self.assertEqual(materialize_candidate_row(FAMILY_EQUAL_WEIGHT_HARD_SWITCH, row), row)
        row["away_metrics"]["season"] = 2023
        with self.assertRaisesRegex(CFBCandidateFamilyError, "WEEK1_PRIOR_SEASON_SWITCH_INVALID"):
            materialize_candidate_row(FAMILY_EQUAL_WEIGHT_HARD_SWITCH, row)

    def test_market_data_is_rejected(self):
        row = self.base_row()
        row["spread"] = -3.5
        with self.assertRaisesRegex(CFBCandidateFamilyError, "MARKET_DATA_PROHIBITED"):
            materialize_candidate_row(FAMILY_EQUAL_WEIGHT_HARD_SWITCH, row)

    def test_baseline_disallows_hidden_tuning_constants(self):
        with self.assertRaisesRegex(CFBCandidateFamilyError, "BASELINE_CONSTANTS_PROHIBITED"):
            materialize_candidate_row(FAMILY_EQUAL_WEIGHT_HARD_SWITCH, self.base_row(), constants={"weight": 0.75})

    def test_other_predeclared_families_still_fail_closed(self):
        for family in ("RELIABILITY_WEIGHTED_HARD_SWITCH", "PRIOR_CURRENT_BLEND", "GAMES_IN_SAMPLE_FEATURE"):
            with self.assertRaisesRegex(CFBCandidateFamilyError, "FAMILY_UNIMPLEMENTED"):
                materialize_candidate_row(family, self.base_row())


if __name__ == "__main__":
    unittest.main()
