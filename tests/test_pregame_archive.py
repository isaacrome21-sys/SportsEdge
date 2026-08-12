import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from sportsedge.pregame_archive import update_pregame_archive


def game(pk, status, start):
    return SimpleNamespace(game_pk=pk, status=status, game_date=start, away_name="A", home_name="H")


class PregameArchiveTests(unittest.TestCase):
    def test_pregame_run_archives_rows(self):
        now = datetime(2026,8,12,1,0,tzinfo=timezone.utc)
        out = update_pregame_archive(
            schedule=[game(7,"Preview","2026-08-12T02:00:00Z")], now=now,
            card_payload={"generated_at_utc":now.isoformat(),"results":[{"game_id":"7","market":"HITS","bet_status":"PASS"}]},
            game_odds_payload={"generated_at_utc":now.isoformat(),"quotes":[{"game_id":"7","market":"MONEYLINE"}]},
        )
        self.assertIn("7", out["games"])
        self.assertEqual(out["games"]["7"]["archive_kind"], "LAST_VALID_PREGAME_EVIDENCE")

    def test_started_game_cannot_overwrite_prior_pregame_snapshot(self):
        prior = {"games":{"7":{"game_id":"7","card_rows":[{"model_p":.6}],"marker":"old"}}}
        now = datetime(2026,8,12,3,0,tzinfo=timezone.utc)
        out = update_pregame_archive(
            schedule=[game(7,"Live","2026-08-12T02:00:00Z")], now=now, prior=prior,
            card_payload={"results":[{"game_id":"7","model_p":.99}]},
            game_odds_payload={"quotes":[{"game_id":"7","american_odds":999}]},
        )
        self.assertEqual(out["games"]["7"]["marker"], "old")
        self.assertEqual(out["games"]["7"]["card_rows"][0]["model_p"], .6)

    def test_no_rows_does_not_destroy_existing_archive(self):
        prior={"games":{"7":{"game_id":"7","marker":"keep"}}}
        now=datetime(2026,8,12,1,0,tzinfo=timezone.utc)
        out=update_pregame_archive(schedule=[game(7,"Preview","2026-08-12T02:00:00Z")],now=now,prior=prior)
        self.assertEqual(out["games"]["7"]["marker"],"keep")

if __name__ == "__main__": unittest.main()
