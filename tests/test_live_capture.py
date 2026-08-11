import unittest

from sportsedge.live_capture import capture_slate
from sportsedge.mlb_source import GameSnapshot


def snap(pk=1):
    return GameSnapshot(
        game_pk=pk, game_date="2026-08-10T23:00:00Z", status="Preview",
        away_id=10, away_name="Away", home_id=20, home_name="Home",
        away_probable_pitcher_id=101, away_probable_pitcher_name="A",
        home_probable_pitcher_id=202, home_probable_pitcher_name="H",
        retrieved_at="2026-08-10T20:00:00+00:00",
    )


def box(primary_away=9, primary_home=9):
    def team(start, count):
        players = {}
        for i in range(count):
            pid = start + i
            players[f"ID{pid}"] = {
                "person": {"id": pid, "fullName": f"P{pid}"},
                "battingOrder": (i + 1) * 100,
            }
        return {"players": players}
    return {"teams": {"away": team(100, primary_away), "home": team(200, primary_home)}}


class LiveCaptureTests(unittest.TestCase):
    def test_both_nine_lineups_confirmed(self):
        out = capture_slate("2026-08-10", schedule_fetcher=lambda d: [snap()], boxscore_fetcher=lambda pk: box())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].status, "LINEUPS_CONFIRMED")
        self.assertTrue(out[0].live_game.away_lineup.confirmed)
        self.assertTrue(out[0].live_game.home_lineup.confirmed)

    def test_partial_lineup_is_explicit(self):
        out = capture_slate("2026-08-10", schedule_fetcher=lambda d: [snap()], boxscore_fetcher=lambda pk: box(8, 9))
        self.assertEqual(out[0].status, "LINEUPS_PARTIAL")
        self.assertFalse(out[0].live_game.away_lineup.confirmed)

    def test_no_lineups_is_explicit(self):
        out = capture_slate("2026-08-10", schedule_fetcher=lambda d: [snap()], boxscore_fetcher=lambda pk: box(0, 0))
        self.assertEqual(out[0].status, "LINEUPS_UNAVAILABLE")

    def test_boxscore_failure_does_not_silently_drop_game(self):
        def fail(pk):
            raise RuntimeError("network down")
        out = capture_slate("2026-08-10", schedule_fetcher=lambda d: [snap()], boxscore_fetcher=fail)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].status, "CAPTURE_BLOCKED")
        self.assertIn("network down", out[0].error)

    def test_duplicate_game_pk_is_blocked_as_second_record(self):
        out = capture_slate("2026-08-10", schedule_fetcher=lambda d: [snap(1), snap(1)], boxscore_fetcher=lambda pk: box())
        self.assertEqual(out[0].status, "LINEUPS_CONFIRMED")
        self.assertEqual(out[1].status, "CAPTURE_BLOCKED")
        self.assertIn("duplicate", out[1].error)


if __name__ == "__main__":
    unittest.main()
