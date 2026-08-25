import unittest
from datetime import date, datetime, timezone

from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.pitcher_record_win_engine import (
    PITCHER_RECORD_WIN_ENGINE_VERSION,
    build_pitcher_record_win_features,
    build_shared_pitcher_record_win_engine_session,
)


class _Source:
    retrieved_at = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    opener = None

    def __init__(self, outs=(15, 15, 15, 15, 15), wins=(1, 0, 1, 0, 1)):
        self.outs = tuple(outs)
        self.wins = tuple(wins)

    @staticmethod
    def _ip(outs):
        return f"{outs // 3}.{outs % 3}"

    def player_rows(self, *, player_id, group, target_date):
        assert group == "pitching"
        rows = []
        for index, (outs, win) in enumerate(zip(self.outs, self.wins), 1):
            rows.append({
                "date": date(2026, 8, index),
                "stat": {
                    "gamesStarted": 1,
                    "wins": win,
                    "losses": 1 - win,
                    "inningsPitched": self._ip(outs),
                },
            })
        return rows


class _F5Source:
    retrieved_at = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)

    def __init__(self, *, state="LEAD", paths=None):
        self.state = state
        self.paths = paths or {
            "LEAD": [15, 15, 15, 15, 15],
            "TIE": [18, 18, 18, 18, 18],
            "TRAIL": [21, None, 21, None, 21],
        }

    def matchup_features(self, *, away_team_id, home_team_id, target_date):
        if self.state == "LEAD":
            # Deterministic HOME lead, 1-0.
            features = {
                "away_f5_runs_for": [0] * 10,
                "away_f5_runs_against": [1] * 10,
                "home_f5_runs_for": [1] * 10,
                "home_f5_runs_against": [0] * 10,
            }
        elif self.state == "TIE":
            features = {
                "away_f5_runs_for": [0] * 10,
                "away_f5_runs_against": [0] * 10,
                "home_f5_runs_for": [0] * 10,
                "home_f5_runs_against": [0] * 10,
            }
        else:
            # Deterministic HOME trail, 0-1.
            features = {
                "away_f5_runs_for": [1] * 10,
                "away_f5_runs_against": [0] * 10,
                "home_f5_runs_for": [0] * 10,
                "home_f5_runs_against": [1] * 10,
            }
        return {
            "feature_version": "test_f5",
            "feature_source_hash": "1" * 64,
            "features": features,
        }

    def win_credit_transition_features(self, *, team_id, target_date):
        return {
            "feature_version": "test_credit",
            "feature_source_hash": "2" * 64,
            "history_games": sum(len(v) for v in self.paths.values()),
            "state_counts": {state: len(values) for state, values in self.paths.items()},
            "paths": {state: list(values) for state, values in self.paths.items()},
        }


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


def _features(*, outs, state="LEAD", paths=None):
    built = build_pitcher_record_win_features(
        _Source(outs=outs),
        game=_game(),
        pitcher_id=222,
        target_date=date(2026, 8, 25),
        f5_source=_F5Source(state=state, paths=paths),
    )
    return {
        "starter_outs_history": list(built["starter_outs_history"]),
        "f5_features": dict(built["f5_features"]),
        "post_f5_credit_paths": {
            key: list(value) for key, value in built["post_f5_credit_paths"].items()
        },
        "game_source_hash": built["game_source_hash"],
        "pitcher_source_hash": built["pitcher_source_hash"],
        "f5_feature_source_hash": built["f5_feature_source_hash"],
        "credit_path_source_hash": built["credit_path_source_hash"],
    }


def _input(*, outs, state="LEAD", paths=None, side="YES", line=0.5):
    return {
        "game_id": "123",
        "market": "PITCHER_RECORD_WIN",
        "entity_id": "222",
        "line": line,
        "side": side,
        "team_side": "HOME",
        "features": _features(outs=outs, state=state, paths=paths),
    }


class PitcherRecordWinCreditStateTests(unittest.TestCase):
    def test_features_use_workload_and_score_paths_not_historical_wins(self):
        source_a = _Source(outs=(15, 18, 15, 21, 12), wins=(1, 1, 1, 1, 1))
        source_b = _Source(outs=(15, 18, 15, 21, 12), wins=(0, 0, 0, 0, 0))
        f5 = _F5Source(state="LEAD")
        a = build_pitcher_record_win_features(
            source_a, game=_game(), pitcher_id=222,
            target_date=date(2026, 8, 25), f5_source=f5,
        )
        b = build_pitcher_record_win_features(
            source_b, game=_game(), pitcher_id=222,
            target_date=date(2026, 8, 25), f5_source=f5,
        )
        self.assertEqual(a["feature_version"], PITCHER_RECORD_WIN_ENGINE_VERSION)
        self.assertEqual(a["feature_source_hash"], b["feature_source_hash"])
        self.assertEqual(a["starter_outs_history"], [15, 18, 15, 21, 12])
        self.assertAlmostEqual(a["qualification_rate"], 0.8)
        self.assertNotIn("decision_rate", a)
        self.assertNotIn("wins", repr(a["history"]))

    def test_five_inning_qualification_is_mandatory_for_f5_lead(self):
        engine = build_shared_pitcher_record_win_engine_session()
        qualified = engine(_input(outs=(15, 15, 15, 15, 15), state="LEAD"))
        short = engine(_input(outs=(12, 12, 12, 12, 12), state="LEAD"))
        self.assertAlmostEqual(qualified["model_p"], 1.0)
        self.assertAlmostEqual(short["model_p"], 0.0)
        self.assertAlmostEqual(qualified["qualification_rate"], 1.0)
        self.assertAlmostEqual(short["qualification_rate"], 0.0)

    def test_exit_depth_controls_tie_to_permanent_lead_credit(self):
        paths = {"LEAD": [], "TIE": [18, 18, 18, 18, 18], "TRAIL": []}
        engine = build_shared_pitcher_record_win_engine_session()
        six_inning = engine(_input(outs=(18, 18, 18, 18, 18), state="TIE", paths=paths))
        five_inning = engine(_input(outs=(15, 15, 15, 15, 15), state="TIE", paths=paths))
        self.assertAlmostEqual(six_inning["f5_state_probabilities"]["TIE"], 1.0)
        self.assertAlmostEqual(six_inning["model_p"], 1.0)
        self.assertAlmostEqual(five_inning["model_p"], 0.0)

    def test_bullpen_late_game_path_failure_contributes_zero(self):
        paths = {"LEAD": [15, None, 15, None, 15], "TIE": [], "TRAIL": []}
        engine = build_shared_pitcher_record_win_engine_session()
        result = engine(_input(outs=(18, 18, 18, 18, 18), state="LEAD", paths=paths))
        self.assertAlmostEqual(result["credit_probability_by_state"]["LEAD"], 0.6)
        self.assertAlmostEqual(result["model_p"], 0.6)

    def test_yes_no_and_quote_line_share_same_latent_identity(self):
        engine = build_shared_pitcher_record_win_engine_session()
        yes = engine(_input(outs=(15, 18, 18, 21, 21), state="LEAD", side="YES", line=0.5))
        no = engine(_input(outs=(15, 18, 18, 21, 21), state="LEAD", side="NO", line=1.5))
        self.assertAlmostEqual(yes["model_p"] + no["model_p"], 1.0)
        self.assertEqual(yes["model_input_hash"], no["model_input_hash"])
        self.assertEqual(yes["distribution_sha256"], no["distribution_sha256"])
        self.assertNotEqual(yes["readout_sha256"], no["readout_sha256"])
        self.assertEqual(yes["seed_policy"], "analytic_f5_score_path_x_starter_outs_cross_product")
        self.assertEqual(yes["mc_paths"], 0)

    def test_missing_credit_history_for_live_f5_state_fails_closed(self):
        paths = {"LEAD": [], "TIE": [18], "TRAIL": []}
        engine = build_shared_pitcher_record_win_engine_session()
        with self.assertRaisesRegex(Exception, "CREDIT_PATH_STATE_MISSING:LEAD"):
            engine(_input(outs=(18, 18, 18, 18, 18), state="LEAD", paths=paths))


if __name__ == "__main__":
    unittest.main()
