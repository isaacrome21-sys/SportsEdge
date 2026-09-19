from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.sports.cfb.joint_model import CFBJointScoreModel, CFB_FEATURE_CONTRACT, CFB_JOINT_MODEL_ID, _feature_names
from sportsedge.sports.cfb.run_machine import CFBRunMachineError, run_cfb_machine
from sportsedge.sports.cfb.source import CFBGame, CFBQuote, CFBTeamMetrics

NOW = datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc)
START = datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)


def _metric(team: str, bump: float = 0.0) -> CFBTeamMetrics:
    return CFBTeamMetrics(
        team=team, season=2025, through_week=99, sample_source="PRIOR_SEASON_FALLBACK",
        off_ppa_rush=.11+bump, off_ppa_dropback=.19+bump, def_ppa_rush_allowed=.05-bump,
        def_ppa_dropback_allowed=.08-bump, off_success_rate=.46+bump/10,
        def_success_rate_allowed=.42-bump/10, standard_down_ppa=.13+bump,
        passing_down_success_rate=.39+bump/10, eckel_rate=.31+bump/10,
        points_per_eckel=4.7+bump, points_per_drive=2.3+bump, net_field_position=1.8+bump,
        explosive_rate=.12+bump/10, feature_asof_ts=NOW.isoformat(),
    )


def _game() -> CFBGame:
    return CFBGame(
        "1001", 2026, 1, START.isoformat(), "Alpha State", "Beta Tech", False,
        "Test Stadium", {"game_indoor": False, "wind_speed": 7.0, "temperature": 76.0},
    )


def _model() -> CFBJointScoreModel:
    n = len(_feature_names())
    return CFBJointScoreModel(
        CFB_JOINT_MODEL_ID, CFB_FEATURE_CONTRACT, _feature_names(), (0.0,)*n, (1.0,)*n,
        (28.0,)+(0.0,)*n, (21.0,)+(0.0,)*n,
        ((0.0,0.0),(1.0,-1.0),(-1.0,1.0),(2.0,0.0)),
        ((6,0),(0,6)), (2024,2025), 10.0,
    )


def _quote(market: str, side: str, line: float, odds: float, *, period: str = "FG") -> CFBQuote:
    ts = (NOW - timedelta(seconds=20)).isoformat()
    return CFBQuote(
        game_id="1001", period=period, market=market, entity_id="1001", side=side,
        line=line, american_odds=odds, book_key="draftkings", sportsbook="DraftKings",
        retrieved_at=ts, offer_id=f"{market}-{side}-{line}", is_alternate=market.startswith("ALTERNATE_"),
    )


class CFBFullGameDerivativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.games = [_game()]
        self.metrics = {"Alpha State": _metric("Alpha State"), "Beta Tech": _metric("Beta Tech", .02)}
        self.teams = [
            {"school": "Alpha State", "abbreviation": "ASU", "mascot": "Owls", "alternateNames": []},
            {"school": "Beta Tech", "abbreviation": "BT", "mascot": "Bears", "alternateNames": []},
        ]

    def _run(self, quotes):
        return run_cfb_machine(
            mode="MANUAL", season=2026, week=1, model=_model(), now=NOW,
            games=self.games, metrics=self.metrics, quotes=quotes,
            fbs_team_rows=self.teams, n_paths=500, root_seed=44,
        )

    def test_alternate_spread_and_total_reuse_same_distribution_readouts(self):
        quotes = [
            _quote("SPREAD", "HOME", -6.5, -110), _quote("SPREAD", "AWAY", -6.5, -110),
            _quote("ALTERNATE_SPREAD", "HOME", -6.5, -125), _quote("ALTERNATE_SPREAD", "AWAY", -6.5, 105),
            _quote("TOTAL", "OVER", 49.5, -105), _quote("TOTAL", "UNDER", 49.5, -115),
            _quote("ALTERNATE_TOTAL", "OVER", 49.5, 115), _quote("ALTERNATE_TOTAL", "UNDER", 49.5, -135),
        ]
        report = self._run(quotes)
        by_key = {(r.market, r.side): r for r in report.results}
        self.assertEqual(by_key[("SPREAD", "HOME")].model_p, by_key[("ALTERNATE_SPREAD", "HOME")].model_p)
        self.assertEqual(by_key[("SPREAD", "AWAY")].push_p, by_key[("ALTERNATE_SPREAD", "AWAY")].push_p)
        self.assertEqual(by_key[("TOTAL", "OVER")].model_p, by_key[("ALTERNATE_TOTAL", "OVER")].model_p)
        self.assertEqual(len({r.distribution_sha256 for r in report.results}), 1)
        self.assertTrue(all(r.reason == "CFB_PROMOTION_EVIDENCE_REQUIRED" for r in report.results))
        self.assertTrue(all(r.bet_status == "BLOCKED" for r in report.results))

    def test_home_and_away_team_totals_price_from_same_joint_paths(self):
        report = self._run([
            _quote("HOME_TEAM_TOTAL", "OVER", 27.5, -110), _quote("HOME_TEAM_TOTAL", "UNDER", 27.5, -110),
            _quote("AWAY_TEAM_TOTAL", "OVER", 21.5, -105), _quote("AWAY_TEAM_TOTAL", "UNDER", 21.5, -115),
        ])
        self.assertEqual({r.market for r in report.results}, {"HOME_TEAM_TOTAL", "AWAY_TEAM_TOTAL"})
        self.assertEqual(len({r.distribution_sha256 for r in report.results}), 1)
        self.assertTrue(all(r.engine_status == "PRICED" for r in report.results))
        self.assertTrue(all(r.model_p is not None and r.push_p is not None for r in report.results))
        self.assertEqual(report.summary["official_bets"], 0)

    def test_full_game_engines_reject_non_full_game_period(self):
        with self.assertRaisesRegex(CFBRunMachineError, "CFB_FULL_GAME_PERIOD_REQUIRED:MONEYLINE:1H"):
            self._run([_quote("MONEYLINE", "HOME", 0.0, -150, period="1H")])

    def test_true_period_market_remains_no_engine_instead_of_using_final_scores(self):
        report = self._run([_quote("FIRST_HALF_TOTAL", "OVER", 24.5, -110, period="1H")])
        result = report.results[0]
        self.assertEqual((result.engine_status, result.bet_status, result.reason), ("NO_ENGINE", "BLOCKED", "NO_ENGINE"))
        self.assertIsNone(result.model_p)


if __name__ == "__main__":
    unittest.main()
