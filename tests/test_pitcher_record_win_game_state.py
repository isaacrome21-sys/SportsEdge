import unittest
from datetime import date, datetime, timezone

from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.pitcher_record_win_engine import (
    build_pitcher_record_win_features,
    build_shared_pitcher_record_win_engine_session,
)
from sportsedge.v7_distribution import GameDistribution


class _Source:
    retrieved_at = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)

    def player_rows(self, *, player_id, group, target_date):
        assert group == "pitching"
        decisions = [(1, 0), (0, 1), (0, 0), (1, 0), (0, 1)]
        rows = []
        for index, (wins, losses) in enumerate(decisions, 1):
            rows.append({
                "date": date(2026, 8, index),
                "stat": {
                    "gamesStarted": 1,
                    "wins": wins,
                    "losses": losses,
                    "inningsPitched": "5.0",
                },
            })
        return rows

    def team_means(self, *, away_team_id, home_team_id, target_date):
        return 4.0, 5.0, None


def _lineup(team_id, side, start):
    return TeamLineup(
        team_id=team_id,
        side=side,
        player_ids=tuple(range(start, start + 9)),
        batting_slots=tuple(range(1, 10)),
        confirmed=True,
    )


def _game():
    return LiveGame(
        game_pk=123,
        away_team_id=10,
        home_team_id=20,
        away_probable_pitcher_id=111,
        home_probable_pitcher_id=222,
        away_lineup=_lineup(10, "away", 1000),
        home_lineup=_lineup(20, "home", 2000),
        venue_id=5,
        official_date="2026-08-25",
        status="Preview",
    )


def _distribution():
    return GameDistribution(
        simulations=1000,
        seed=1,
        seed_policy="identity_sha256_256bit",
        away_mean_runs=4.0,
        home_mean_runs=5.0,
        away_win_probability=0.25,
        home_win_probability=0.75,
        away_plus_1_5_probability=0.25,
        home_minus_1_5_probability=0.75,
        over_probability=0.5,
        under_probability=0.5,
        push_probability=0.0,
        nrfi_probability=0.5,
        yrfi_probability=0.5,
        regulation_tie_probability=0.0,
        first_inning_share=0.118,
        first_inning_dispersion_r=0.35,
        extra_half_inning_mean=0.55,
        joint_score_pmf={"3,4": 0.75, "5,2": 0.25},
        result_sha256="0" * 64,
    )


class PitcherRecordWinGameStateTests(unittest.TestCase):
    def test_features_use_decision_propensity_not_historical_win_rate(self):
        built = build_pitcher_record_win_features(
            _Source(), game=_game(), pitcher_id=222, target_date=date(2026, 8, 25)
        )
        # Four of five starts had a decision; only two were wins. The candidate
        # intentionally carries decision propensity, not the old 2/5 win rate.
        self.assertAlmostEqual(built["decision_rate"], 0.8)
        self.assertAlmostEqual(built["qualification_rate"], 1.0)
        self.assertEqual(built["team_side"], "HOME")
        self.assertEqual(len(built["game_source_hash"]), 64)
        self.assertEqual(len(built["pitcher_source_hash"]), 64)

    def test_today_team_state_multiplies_decision_propensity(self):
        calls = []

        def simulator(**kwargs):
            calls.append(kwargs)
            return _distribution()

        engine = build_shared_pitcher_record_win_engine_session(simulator=simulator)
        common = {
            "game_id": "123",
            "market": "PITCHER_RECORD_WIN",
            "entity_id": "222",
            "line": 0.5,
            "team_side": "HOME",
            "away_mean_runs": 4.0,
            "home_mean_runs": 5.0,
            "features": {
                "decision_rate": 0.8,
                "game_source_hash": "1" * 64,
                "pitcher_source_hash": "2" * 64,
            },
            "simulations": 1000,
        }
        yes = engine({**common, "side": "YES"})
        no = engine({**common, "side": "NO"})
        self.assertAlmostEqual(yes["team_win_probability"], 0.75)
        self.assertAlmostEqual(yes["model_p"], 0.60)
        self.assertAlmostEqual(no["model_p"], 0.40)
        self.assertEqual(len(calls), 1)
        self.assertEqual(yes["distribution_sha256"], no["distribution_sha256"])
        self.assertEqual(yes["model_input_hash"], no["model_input_hash"])
        self.assertNotEqual(yes["readout_sha256"], no["readout_sha256"])

    def test_two_pitchers_share_same_game_distribution(self):
        calls = []

        def simulator(**kwargs):
            calls.append(kwargs)
            return _distribution()

        engine = build_shared_pitcher_record_win_engine_session(simulator=simulator)
        home = engine({
            "game_id": "123", "market": "PITCHER_RECORD_WIN", "entity_id": "222",
            "line": 0.5, "side": "YES", "team_side": "HOME",
            "away_mean_runs": 4.0, "home_mean_runs": 5.0, "simulations": 1000,
            "features": {"decision_rate": 0.8, "game_source_hash": "1" * 64, "pitcher_source_hash": "2" * 64},
        })
        away = engine({
            "game_id": "123", "market": "PITCHER_RECORD_WIN", "entity_id": "111",
            "line": 0.5, "side": "YES", "team_side": "AWAY",
            "away_mean_runs": 4.0, "home_mean_runs": 5.0, "simulations": 1000,
            "features": {"decision_rate": 0.6, "game_source_hash": "1" * 64, "pitcher_source_hash": "3" * 64},
        })
        self.assertEqual(len(calls), 1)
        self.assertEqual(home["distribution_sha256"], away["distribution_sha256"])
        self.assertAlmostEqual(away["model_p"], 0.25 * 0.6)


if __name__ == "__main__":
    unittest.main()
