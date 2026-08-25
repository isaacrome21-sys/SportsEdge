import json
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest

from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.mlb_generic_features import MLBGenericFeatureError, MLBGenericHistorySource
from sportsedge.pitcher_win_state_engine import (
    build_pitcher_win_features,
    build_shared_pitcher_win_engine_session,
    simulate_pitcher_win_distribution,
    starter_win_credit,
)
from sportsedge.prediction_journal import PredictionJournalError, write_prediction_journal


class _Source:
    def __init__(self, *, outs=18):
        self.retrieved_at = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
        self.outs = outs

    def player_rows(self, *, player_id, group, target_date):
        self.assert_group = group
        rows = []
        for i in range(12):
            whole, frac = divmod(self.outs, 3)
            rows.append({
                "date": date(2026, 8, i + 1),
                "stat": {
                    "gamesStarted": 1,
                    "inningsPitched": f"{whole}.{frac}",
                    "earnedRuns": 1 if player_id == 501 else 2,
                    # Deliberately present. The rebuilt model must ignore it.
                    "wins": 1 if i % 2 == 0 else 0,
                },
            })
        return rows

    def team_means(self, *, away_team_id, home_team_id, target_date):
        return 5.2, 4.4, 2.0


def _lineup(team_id, side, start):
    return TeamLineup(
        team_id,
        side,
        tuple(range(start, start + 9)),
        tuple(range(1, 10)),
        True,
    )


def _game():
    return LiveGame(
        game_pk=777,
        away_team_id=10,
        home_team_id=20,
        away_probable_pitcher_id=501,
        home_probable_pitcher_id=601,
        away_lineup=_lineup(10, "away", 100),
        home_lineup=_lineup(20, "home", 200),
        venue_id=1,
        official_date="2026-08-25",
        status="Preview",
    )


def _features(*, away_outs=18, home_outs=18):
    def rows(outs, er):
        return [{"outs": outs, "earned_runs": er} for _ in range(12)]
    return {
        "away_team_id": 10,
        "home_team_id": 20,
        "away_starter_id": 501,
        "home_starter_id": 601,
        "away_team_mean_runs": 5.2,
        "home_team_mean_runs": 4.4,
        "away_starter_history": rows(away_outs, 1),
        "home_starter_history": rows(home_outs, 2),
    }


class PitcherWinStateTests(unittest.TestCase):
    def test_feature_builder_excludes_historical_win_decisions(self):
        built = build_pitcher_win_features(
            _Source(), game=_game(), target_date=date(2026, 8, 25)
        )
        encoded = json.dumps(built, sort_keys=True)
        self.assertNotIn('"wins"', encoded)
        self.assertEqual(built["features"]["away_starter_id"], 501)
        self.assertEqual(built["features"]["home_starter_id"], 601)
        self.assertEqual(len(built["feature_source_hash"]), 64)

    def test_legacy_generic_special_market_proxies_are_retired_fail_closed(self):
        calls = []

        def opener(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("legacy special-market path must fail before network fetch")

        source = MLBGenericHistorySource(
            opener=opener,
            retrieved_at=datetime(2026, 8, 25, 15, tzinfo=timezone.utc),
        )
        common = dict(
            game_pk=777,
            entity_id="501",
            target_date=date(2026, 8, 25),
            away_team_id=10,
            home_team_id=20,
            player_id=501,
        )
        for market in ("PITCHER_RECORD_WIN", "FIRST_HOME_RUN"):
            with self.subTest(market=market):
                with self.assertRaisesRegex(MLBGenericFeatureError, "STATEFUL_FEATURE_PATH_REQUIRED"):
                    source.feature_row(market=market, **common)
        with self.assertRaisesRegex(MLBGenericFeatureError, "F5_STATEFUL_FEATURE_PATH_REQUIRED"):
            source.feature_row(
                market="F5_TOTALS",
                game_pk=777,
                entity_id="GAME",
                target_date=date(2026, 8, 25),
                away_team_id=10,
                home_team_id=20,
            )
        self.assertEqual(calls, [])

    def test_starter_win_credit_requires_five_innings_and_preserved_lead(self):
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

    def test_short_starter_has_exactly_zero_win_probability(self):
        result = simulate_pitcher_win_distribution(
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
        engine = build_shared_pitcher_win_engine_session()
        base = {
            "game_id": "777",
            "market": "PITCHER_RECORD_WIN",
            "line": 0.5,
            "features": _features(),
            "feature_source_hash": "b" * 64,
            "simulations": 2000,
        }
        away_yes = engine({**base, "entity_id": "501", "side": "YES"})
        away_no = engine({**base, "entity_id": "501", "side": "NO"})
        home_yes = engine({**base, "entity_id": "601", "side": "YES"})
        self.assertEqual(away_yes["model_input_hash"], away_no["model_input_hash"])
        self.assertEqual(away_yes["model_input_hash"], home_yes["model_input_hash"])
        self.assertEqual(away_yes["distribution_sha256"], away_no["distribution_sha256"])
        self.assertEqual(away_yes["distribution_sha256"], home_yes["distribution_sha256"])
        self.assertNotEqual(away_yes["readout_sha256"], away_no["readout_sha256"])
        self.assertAlmostEqual(away_yes["model_p"] + away_no["model_p"], 1.0, places=12)
        self.assertLessEqual(away_yes["model_p"] + home_yes["model_p"], 1.0 + 1e-12)

    def _journal_payload(self, market):
        return {
            "slate_date_ct": "2026-08-25",
            "generated_at_utc": "2026-08-25T15:00:00+00:00",
            "run_status": "PASS",
            "card_status": "PASS",
            "results": [{
                "game_id": "777",
                "market": market,
                "entity_id": "501",
                "line": 0.5,
                "side": "YES",
                "american_odds": 150,
                "model_p": 0.42,
                "bet_status": "PASS",
                "reason": "ok",
                "model_input_hash": "a" * 64,
                "distribution_sha256": "b" * 64,
                "readout_sha256": "c" * 64,
                "readout_version": "state_readout_v1",
                "engine_version": "state_engine_v1",
                "seed_policy": "identity_sha256_256bit",
                "mc_paths": 2000,
            }],
        }

    def test_stateful_special_markets_require_full_provenance_in_journal(self):
        for market in ("FIRST_HOME_RUN", "PITCHER_RECORD_WIN"):
            with self.subTest(market=market), tempfile.TemporaryDirectory() as tmp:
                result = write_prediction_journal(self._journal_payload(market), root=tmp)
                row = json.loads(Path(result.path).read_text())["predictions"][0]
                self.assertEqual(row["distribution_sha256"], "b" * 64)
                self.assertEqual(row["engine_version"], "state_engine_v1")

        for field in (
            "model_input_hash", "distribution_sha256", "readout_sha256",
            "readout_version", "engine_version", "seed_policy", "mc_paths",
        ):
            payload = self._journal_payload("PITCHER_RECORD_WIN")
            payload["results"][0][field] = None
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(PredictionJournalError, field):
                    write_prediction_journal(payload, root=tmp)


if __name__ == "__main__":
    unittest.main()
