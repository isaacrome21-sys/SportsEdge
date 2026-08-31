from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.sports.cfb.joint_model import CFBJointScoreModel, CFB_FEATURE_CONTRACT, CFB_JOINT_MODEL_ID, _feature_names
from sportsedge.sports.cfb.run_machine import CFBRunMachineError, run_cfb_machine
from sportsedge.sports.cfb.source import CFBGame, CFBQuote, CFBTeamMetrics

UTC = timezone.utc
NOW = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
START = datetime(2026, 9, 12, 19, 30, tzinfo=UTC)
TEAMS = [{"school": "Alpha State"}, {"school": "Beta Tech"}]


def _metric(team: str, *, through_week: int = 1, asof: datetime = NOW, sample_source: str = "CURRENT_SEASON_PRIOR_WEEKS", season: int = 2026) -> CFBTeamMetrics:
    return CFBTeamMetrics(
        team=team, season=season, through_week=through_week, sample_source=sample_source,
        off_ppa_rush=.1, off_ppa_dropback=.2, def_ppa_rush_allowed=.05, def_ppa_dropback_allowed=.08,
        off_success_rate=.45, def_success_rate_allowed=.42, standard_down_ppa=.12,
        passing_down_success_rate=.39, eckel_rate=.3, points_per_eckel=4.5,
        points_per_drive=2.2, net_field_position=1.0, explosive_rate=.1,
        feature_asof_ts=asof.isoformat(),
    )


def _game(*, start: datetime = START) -> CFBGame:
    return CFBGame(
        game_id="g1", season=2026, week=2, start_ts=start.isoformat(),
        home_team="Alpha State", away_team="Beta Tech", neutral_site=False,
        venue="Test", weather={"game_indoor": False, "wind_speed": 5.0, "temperature": 70.0},
    )


def _model() -> CFBJointScoreModel:
    n = len(_feature_names())
    return CFBJointScoreModel(
        CFB_JOINT_MODEL_ID, CFB_FEATURE_CONTRACT, _feature_names(),
        (0.0,) * n, (1.0,) * n,
        (27.0,) + (0.0,) * n, (23.0,) + (0.0,) * n,
        ((0.0, 0.0), (1.0, -1.0)), ((6, 0), (0, 6)), (2024, 2025), 10.0,
    )


def _quotes(*, retrieved: datetime = NOW - timedelta(seconds=10)) -> list[CFBQuote]:
    common = dict(
        game_id="g1", period="FG", market="MONEYLINE", entity_id="g1", line=0.0,
        book_key="draftkings", sportsbook="DraftKings", retrieved_at=retrieved.isoformat(), is_alternate=False,
    )
    return [
        CFBQuote(side="HOME", american_odds=-120, offer_id="h", **common),
        CFBQuote(side="AWAY", american_odds=105, offer_id="a", **common),
    ]


def _run(*, now: datetime = NOW, game: CFBGame | None = None, metrics=None, quotes=None):
    g = game or _game()
    m = metrics or {"Alpha State": _metric("Alpha State"), "Beta Tech": _metric("Beta Tech")}
    q = quotes or _quotes()
    return run_cfb_machine(
        mode="MANUAL", season=2026, week=g.week, model=_model(), now=now,
        games=[g], metrics=m, quotes=q, fbs_team_rows=TEAMS, n_paths=10, root_seed=7,
    )


class CFBPITGuardTests(unittest.TestCase):
    def test_target_week_metrics_are_rejected(self):
        metrics={
            "Alpha State": _metric("Alpha State", through_week=2),
            "Beta Tech": _metric("Beta Tech", through_week=1),
        }
        with self.assertRaisesRegex(CFBRunMachineError, "CFB_TARGET_WEEK_FEATURE_LEAKAGE:Alpha State"):
            _run(metrics=metrics)

    def test_future_feature_snapshot_is_rejected(self):
        metrics={
            "Alpha State": _metric("Alpha State", asof=NOW + timedelta(minutes=1)),
            "Beta Tech": _metric("Beta Tech"),
        }
        with self.assertRaisesRegex(CFBRunMachineError, "CFB_FEATURE_FROM_FUTURE:Alpha State"):
            _run(metrics=metrics)

    def test_started_game_is_rejected_before_model_pricing(self):
        started = _game(start=NOW)
        with self.assertRaisesRegex(CFBRunMachineError, "CFB_GAME_NOT_PREGAME:g1"):
            _run(game=started)

    def test_future_quote_is_rejected(self):
        with self.assertRaisesRegex(CFBRunMachineError, "CFB_QUOTE_FROM_FUTURE:g1"):
            _run(quotes=_quotes(retrieved=NOW + timedelta(seconds=1)))

    def test_week_one_prior_season_fallback_must_really_be_prior_season(self):
        week1 = replace(_game(), week=1)
        bad={
            "Alpha State": _metric("Alpha State", through_week=0, sample_source="PRIOR_SEASON_FALLBACK", season=2026),
            "Beta Tech": _metric("Beta Tech", through_week=0, sample_source="PRIOR_SEASON_FALLBACK", season=2025),
        }
        with self.assertRaisesRegex(CFBRunMachineError, "CFB_PRIOR_SEASON_FALLBACK_INVALID:Alpha State"):
            _run(game=week1, metrics=bad)


if __name__ == "__main__":
    unittest.main()
