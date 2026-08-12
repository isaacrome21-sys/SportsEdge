import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from sportsedge.full_slate_accounting import build_full_slate_accounting
from sportsedge.market_coverage import REQUIRED_MARKET_FAMILIES


def game(pk, status, game_date, away="Away", home="Home"):
    return SimpleNamespace(game_pk=pk, status=status, game_date=game_date, away_name=away, home_name=home)


class FullSlateAccountingTests(unittest.TestCase):
    def test_started_game_remains_visible_but_cannot_create_new_bet(self):
        now = datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)
        schedule = [game(1, "Live", "2026-08-12T00:00:00Z"), game(2, "Preview", "2026-08-12T03:00:00Z")]
        out = build_full_slate_accounting(schedule=schedule, now=now)
        self.assertEqual(out["scheduled_games"], 2)
        by_id = {x["game_id"]: x for x in out["games"]}
        self.assertFalse(by_id["1"]["new_bets_allowed"])
        self.assertEqual(by_id["1"]["reason"], "GAME_ALREADY_STARTED")
        self.assertTrue(by_id["2"]["new_bets_allowed"])
        self.assertEqual(len(by_id["1"]["market_families"]), len(REQUIRED_MARKET_FAMILIES))

    def test_early_game_is_not_silently_omitted_when_only_late_game_has_card_rows(self):
        now = datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)
        schedule = [game(1, "Live", "2026-08-12T00:00:00Z"), game(2, "Preview", "2026-08-12T03:00:00Z")]
        card = {"results": [{"game_id": "2", "market": "HITS", "bet_status": "PASS"}]}
        out = build_full_slate_accounting(schedule=schedule, now=now, card_payload=card)
        self.assertEqual([x["game_id"] for x in out["games"]], ["1", "2"])
        early_hits = next(x for x in out["games"][0]["market_families"] if x["market_family"] == "HITS")
        self.assertEqual(early_hits["state"], "NOT_BETTABLE_GAME_STATE")
        late_hits = next(x for x in out["games"][1]["market_families"] if x["market_family"] == "HITS")
        self.assertEqual(late_hits["state"], "EVALUATED")

    def test_started_game_does_not_reuse_current_run_rows_without_archive(self):
        now = datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)
        schedule = [game(1, "Live", "2026-08-12T00:00:00Z")]
        card = {"results": [{"game_id": "1", "market": "HITS", "bet_status": "OFFICIAL_BET"}]}
        out = build_full_slate_accounting(schedule=schedule, now=now, card_payload=card)
        hits = next(x for x in out["games"][0]["market_families"] if x["market_family"] == "HITS")
        self.assertEqual(hits["state"], "NOT_BETTABLE_GAME_STATE")
        self.assertFalse(out["games"][0]["new_bets_allowed"])

    def test_started_game_uses_archived_pregame_rows_when_current_card_has_none(self):
        now = datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)
        schedule = [game(1, "Live", "2026-08-12T00:00:00Z")]
        archive = {"games": {"1": {"archived_at_utc": "2026-08-11T23:50:00+00:00", "card_rows": [{"game_id":"1","market":"HITS","bet_status":"OFFICIAL_BET"}], "game_quotes": []}}}
        out = build_full_slate_accounting(schedule=schedule, now=now, pregame_archive=archive)
        self.assertTrue(out["games"][0]["pregame_archive_present"])
        hits = next(x for x in out["games"][0]["market_families"] if x["market_family"] == "HITS")
        self.assertEqual(hits["state"], "ARCHIVED_PREGAME_ACTIONABLE")
        self.assertFalse(out["games"][0]["new_bets_allowed"])


if __name__ == "__main__":
    unittest.main()
