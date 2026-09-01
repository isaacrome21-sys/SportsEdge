from __future__ import annotations

from datetime import datetime, timezone
import unittest

from sportsedge.sports.cfb.run_machine import run_cfb_machine
from sportsedge.sports.cfb.source import CFBGame

UTC = timezone.utc
NOW = datetime(2026, 8, 26, 17, 0, tzinfo=UTC)


class _UnusedModel:
    def artifact_sha256(self):
        return "a" * 64


class CFBDerivativeScopeTests(unittest.TestCase):
    def test_teaser_parlay_sgp_and_live_labels_are_no_engine(self):
        game = CFBGame(
            game_id="g1", season=2026, week=1,
            start_ts="2026-08-29T16:00:00+00:00",
            home_team="Alpha State", away_team="Beta Tech", neutral_site=False,
            weather={"game_indoor": True},
        )
        rows=[]
        for market in ("TEASER", "PARLAY", "SGP", "LIVE_MONEYLINE"):
            rows.append({
                "game_id":"g1", "market":market, "side":"HOME", "line":0.0,
                "american_odds":-110, "book_key":"test", "sportsbook":"Test",
                "retrieved_at":"2026-08-26T16:59:30+00:00", "offer_id":market.lower(),
            })
        report = run_cfb_machine(
            mode="MANUAL", season=2026, week=1, model=_UnusedModel(), now=NOW,
            games=[game], metrics={}, quotes=rows,
            fbs_team_rows=[{"school":"Alpha State"},{"school":"Beta Tech"}],
            n_paths=1,
        )
        self.assertEqual(len(report.results), 4)
        self.assertTrue(all(row.engine_status == "NO_ENGINE" for row in report.results))
        self.assertTrue(all(row.bet_status == "BLOCKED" for row in report.results))
        self.assertTrue(all(row.reason == "NO_ENGINE" for row in report.results))
        self.assertTrue(all(row.model_p is None for row in report.results))


if __name__ == "__main__":
    unittest.main()
