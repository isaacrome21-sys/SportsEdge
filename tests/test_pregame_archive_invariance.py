import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from sportsedge.historical_cutoff import stable_sha256
from sportsedge.pregame_archive import update_pregame_archive
from sportsedge.full_slate_accounting import build_full_slate_accounting


def snap(pk, status, start, away="Away", home="Home"):
    return SimpleNamespace(game_pk=pk, status=status, game_date=start, away_name=away, home_name=home)


class PregameArchiveInvarianceTests(unittest.TestCase):
    def test_early_game_archived_evidence_is_identical_at_6pm_and_11pm_queries(self):
        schedule_pregame = [snap(1, "Preview", "2026-08-12T00:00:00Z")]
        pre = datetime(2026, 8, 11, 23, 0, tzinfo=timezone.utc)
        original_card = {
            "generated_at_utc": "2026-08-11T22:59:00+00:00",
            "results": [{"game_id": "1", "market": "MONEYLINE", "bet_status": "OFFICIAL_BET", "model_p": 0.57}],
        }
        original_odds = {
            "generated_at_utc": "2026-08-11T22:59:30+00:00",
            "quotes": [{"game_id": "1", "market": "MONEYLINE", "price": -110}],
        }
        archive = update_pregame_archive(
            schedule=schedule_pregame, now=pre, card_payload=original_card, game_odds_payload=original_odds
        )
        original_hash = stable_sha256(archive["games"]["1"])

        # At both later queries the current-run rows are deliberately different.
        # They must never overwrite the pregame archive after first pitch.
        changed_card = {"generated_at_utc": "2026-08-12T00:30:00+00:00", "results": [
            {"game_id": "1", "market": "MONEYLINE", "bet_status": "OFFICIAL_BET", "model_p": 0.99}
        ]}
        changed_odds = {"generated_at_utc": "2026-08-12T00:30:00+00:00", "quotes": [
            {"game_id": "1", "market": "MONEYLINE", "price": +900}
        ]}
        live_schedule = [snap(1, "Live", "2026-08-12T00:00:00Z")]
        six_pm = update_pregame_archive(
            schedule=live_schedule, now=datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc),
            prior=archive, card_payload=changed_card, game_odds_payload=changed_odds,
        )
        eleven_pm = update_pregame_archive(
            schedule=live_schedule, now=datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc),
            prior=six_pm, card_payload=changed_card, game_odds_payload=changed_odds,
        )
        self.assertEqual(stable_sha256(six_pm["games"]["1"]), original_hash)
        self.assertEqual(stable_sha256(eleven_pm["games"]["1"]), original_hash)
        self.assertEqual(six_pm["games"]["1"], eleven_pm["games"]["1"])

    def test_full_day_pipeline_is_byte_stable_from_scratch_for_same_inputs(self):
        now = datetime(2026, 8, 11, 23, 0, tzinfo=timezone.utc)
        schedule = [
            snap(1, "Preview", "2026-08-12T00:00:00Z", "A", "B"),
            snap(2, "Preview", "2026-08-12T03:00:00Z", "C", "D"),
        ]
        card = {"generated_at_utc": "2026-08-11T22:59:00+00:00", "results": [
            {"game_id": "1", "market": "MONEYLINE", "bet_status": "PASS", "model_p": 0.51},
            {"game_id": "2", "market": "NRFI", "bet_status": "OFFICIAL_BET", "model_p": 0.59},
        ]}
        odds = {"generated_at_utc": "2026-08-11T22:59:30+00:00", "quotes": [
            {"game_id": "1", "market": "MONEYLINE", "price": -105},
            {"game_id": "2", "market": "NRFI", "price": -110},
        ]}

        def run_once():
            archive = update_pregame_archive(
                schedule=schedule, now=now, prior=None, card_payload=card, game_odds_payload=odds
            )
            accounting = build_full_slate_accounting(
                schedule=schedule, now=now, card_payload=card, game_odds_payload=odds, pregame_archive=archive
            )
            return {"archive": archive, "accounting": accounting}

        first = run_once()
        second = run_once()
        self.assertEqual(first, second)
        self.assertEqual(stable_sha256(first), stable_sha256(second))

    def test_started_game_current_rows_cannot_replace_archived_pregame_rows(self):
        archive = {"games": {"1": {
            "game_id": "1", "archived_at_utc": "2026-08-11T23:00:00+00:00",
            "card_rows": [{"game_id": "1", "market": "MONEYLINE", "bet_status": "OFFICIAL_BET", "model_p": 0.57}],
            "game_quotes": [{"game_id": "1", "market": "MONEYLINE", "price": -110}],
        }}}
        current = {"results": [{"game_id": "1", "market": "MONEYLINE", "bet_status": "PASS", "model_p": 0.99}]}
        current_odds = {"quotes": [{"game_id": "1", "market": "MONEYLINE", "price": +900}]}
        out = build_full_slate_accounting(
            schedule=[snap(1, "Live", "2026-08-12T00:00:00Z")],
            now=datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc),
            card_payload=current, game_odds_payload=current_odds, pregame_archive=archive,
        )
        ml = next(x for x in out["games"][0]["market_families"] if x["market_family"] == "MONEYLINE")
        self.assertEqual(ml["state"], "ARCHIVED_PREGAME_ACTIONABLE")
        self.assertEqual(ml["bet_status_counts"], {"OFFICIAL_BET": 1})
        self.assertFalse(out["games"][0]["new_bets_allowed"])


if __name__ == "__main__":
    unittest.main()
