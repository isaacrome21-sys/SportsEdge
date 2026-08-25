import json
import unittest
from datetime import date, datetime, timezone

from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.mlb_generic_features import MLBGenericFeatureError, MLBGenericHistorySource
from sportsedge.pitcher_record_win_engine import (
    build_pitcher_record_win_features,
    build_shared_pitcher_record_win_engine_session,
    simulate_pitcher_record_win_distribution,
    starter_win_credit,
)


class _Source:
    retrieved_at = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)

    def __init__(self, *, away_outs=18, home_outs=18):
        self.away_outs = away_outs
        self.home_outs = home_outs

    def player_rows(self, *, player_id, group, target_date):
        assert group == "pitching"
        outs = self.away_outs if player_id == 111 else self.home_outs
        whole, frac = divmod(outs, 3)
        rows = []
        for index in range(12):
            rows.append({
                "date": date(2026, 8, index + 1),
                "stat": {
                    "gamesStarted": 1,
                    "inningsPitched": f"{whole}.{frac}",
                    "earnedRuns": 1 if player_id == 111 else 2,
                    # These are deliberately present to prove the rebuilt feature
                    # contract never consumes historical pitcher decisions.
                    "wins": 1 if index % 2 == 0 else 0,
                    "losses": 0 if index % 2 == 0 else 1,
                },
            })
        return rows

    def team_means(self, *, away_team_id, home_team_id, target_date):
        return 4.6, 5.1, None


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


def _features(*, away_outs=18, home_outs=18):
    def rows(outs, er):
        return [{"outs": outs, "earned_runs": er} for _ in range(12)]
    return {
        "away_team_id": 10,
        "home_team_id": 20,
        "away_starter_id": 111,
        "home_starter_id": 222,
        "away_team_mean_runs": 4.6,
        "home_team_mean_runs": 5.1,
        "away_starter_history": rows(away_outs, 1),
        "home_starter_history": rows(home_outs, 2),
    }


class PitcherRecordWinGameStateTests(unittest.TestCase):
    def test_features_exclude_historical_win_loss_decisions_and_bind_both_starters(self):
        away = build_pitcher_record_win_features(
            _Source(), game=_game(), pitcher_id=111, target_date=date(2026, 8, 25)
        )
        home = build_pitcher_record_win_features(
            _Source(), game=_game(), pitcher_id=222, target_date=date(2026, 8, 25)
        )
        self.assertEqual(away["team_side"], "AWAY")
        self.assertEqual(home["team_side"], "HOME")
        self.assertEqual(away["feature_source_hash"], home["feature_source_hash"])
        self.assertEqual(away["features"], home["features"])
        self.assertEqual(away["features"]["away_starter_id"], 111)
        self.assertEqual(away["features"]["home_starter_id"], 222)
        encoded = json.dumps(away["features"], sort_keys=True)
        self.assertNotIn('"wins"', encoded)
        self.assertNotIn('"losses"', encoded)
        self.assertIsNone(away["decision_rate"])
        self.assertIsNone(away["qualification_rate"])

    def test_legacy_generic_binary_proxies_fail_before_any_history_fetch(self):
        calls = []

        def opener(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("stateful binary fallback must fail before network access")

        source = MLBGenericHistorySource(
            opener=opener,
            retrieved_at=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        )
        common = dict(
            game_pk=123,
            entity_id="222",
            target_date=date(2026, 8, 25),
            away_team_id=10,
            home_team_id=20,
            player_id=222,
        )
        for market in ("PITCHER_RECORD_WIN", "FIRST_HOME_RUN"):
            with self.subTest(market=market):
                with self.assertRaisesRegex(MLBGenericFeatureError, "STATEFUL_FEATURE_PATH_REQUIRED"):
                    source.feature_row(market=market, **common)
        self.assertEqual(calls, [])

    def test_starter_credit_requires_five_innings_lead_and_lead_preservation(self):
        self.assertFalse(starter_win_credit(
            outs_recorded=14, leading_at_exit=True, lead_relinquished=False
        ))
        self.assertFalse(starter_win_credit(
            outs_recorded=18, leading_at_exit=False, lead_relinquished=False
        ))
        self.assertFalse(starter_win_credit(
            outs_recorded=18, leading_at_exit=True, lead_relinquished=True
        ))
        self.assertTrue(starter_win_credit(
            outs_recorded=18, leading_at_exit=True, lead_relinquished=False
        ))

    def test_sub_five_inning_starter_has_exactly_zero_win_probability(self):
        result = simulate_pitcher_record_win_distribution(
            _features(away_outs=14, home_outs=18),
            simulations=2000,
            build_hash="a" * 64,
        )
        self.assertEqual(result.away_starter_win_probability, 0.0)
        self.assertGreaterEqual(result.home_starter_win_probability, 0.0)
        self.assertAlmostEqual(
            result.away_starter_win_probability
            + result.home_starter_win_probability
            + result.no_starting_pitcher_win_probability,
            1.0,
            places=12,
        )

    def test_both_starters_and_yes_no_share_one_latent_distribution(self):
        engine = build_shared_pitcher_record_win_engine_session()
        common = {
            "game_id": "123",
            "market": "PITCHER_RECORD_WIN",
            "line": 0.5,
            "features": _features(),
            "feature_source_hash": "1" * 64,
            "simulations": 2000,
        }
        away_yes = engine({**common, "entity_id": "111", "side": "YES"})
        away_no = engine({**common, "entity_id": "111", "side": "NO"})
        home_yes = engine({**common, "entity_id": "222", "side": "YES"})
        self.assertEqual(away_yes["model_input_hash"], away_no["model_input_hash"])
        self.assertEqual(away_yes["model_input_hash"], home_yes["model_input_hash"])
        self.assertEqual(away_yes["distribution_sha256"], away_no["distribution_sha256"])
        self.assertEqual(away_yes["distribution_sha256"], home_yes["distribution_sha256"])
        self.assertNotEqual(away_yes["readout_sha256"], away_no["readout_sha256"])
        self.assertNotEqual(away_yes["readout_sha256"], home_yes["readout_sha256"])
        self.assertAlmostEqual(away_yes["model_p"] + away_no["model_p"], 1.0, places=12)
        self.assertLessEqual(away_yes["model_p"] + home_yes["model_p"], 1.0 + 1e-12)

    def test_v1_final_score_simulator_hook_cannot_bypass_exit_state(self):
        calls = []

        def old_shortcut(**kwargs):
            calls.append(kwargs)
            raise AssertionError("v1 final-score shortcut must not execute")

        engine = build_shared_pitcher_record_win_engine_session(simulator=old_shortcut)
        row = engine({
            "game_id": "123",
            "market": "PITCHER_RECORD_WIN",
            "entity_id": "111",
            "line": 0.5,
            "side": "YES",
            "features": _features(),
            "feature_source_hash": "2" * 64,
            "simulations": 1000,
        })
        self.assertEqual(calls, [])
        self.assertEqual(row["engine_version"], "mlb_pitcher_record_win_exit_bullpen_v2_candidate")


if __name__ == "__main__":
    unittest.main()
