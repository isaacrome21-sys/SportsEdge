import unittest

from sportsedge.mlb_source import GameSnapshot
from sportsedge.odds_normalization import OddsNormalizationError, dedupe_latest, normalize_quote


def game(pk=777, start="2026-08-16T19:05:00Z", number=1):
    return GameSnapshot(
        game_pk=pk, game_date=start, status="Preview",
        away_id=1, away_name="Away", home_id=2, home_name="Home",
        away_probable_pitcher_id=11, away_probable_pitcher_name="A",
        home_probable_pitcher_id=22, home_probable_pitcher_name="H",
        retrieved_at="2026-08-16T15:00:00+00:00", game_number=number,
    )


def quote(*, updated="2026-08-16T17:00:00Z", fetched="2026-08-16T17:01:00Z", price=-110, line=0.5, pk=777):
    return normalize_quote(
        provider_event_id=f"evt-{pk}", game=game(pk=pk), bookmaker_key="DraftKings",
        market="HITS", selection="OVER", line=line, american_price=price,
        provider_last_update=updated, sportsedge_fetched_at=fetched,
    )


class OddsNormalizationTests(unittest.TestCase):
    def test_normalizes_identity_and_decimal_price(self):
        q = quote()
        self.assertEqual(q.mlb_game_pk, 777)
        self.assertEqual(q.bookmaker_key, "draftkings")
        self.assertTrue(q.sportsedge_game_id.startswith("MLB:777:"))
        self.assertAlmostEqual(q.decimal_price, 1 + 100/110)

    def test_rejects_post_first_pitch_fetch(self):
        with self.assertRaises(OddsNormalizationError):
            quote(fetched="2026-08-16T19:05:00Z", updated="2026-08-16T19:04:00Z")

    def test_rejects_provider_time_after_fetch(self):
        with self.assertRaises(OddsNormalizationError):
            quote(updated="2026-08-16T17:02:00Z", fetched="2026-08-16T17:01:00Z")

    def test_latest_provider_update_wins(self):
        older = quote(updated="2026-08-16T17:00:00Z", price=-110)
        newer = quote(updated="2026-08-16T17:02:00Z", fetched="2026-08-16T17:03:00Z", price=-105)
        out = dedupe_latest([newer, older])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].american_price, -105)

    def test_same_timestamp_conflicting_duplicate_fails(self):
        a = quote(price=-110)
        b = quote(price=-105)
        with self.assertRaises(OddsNormalizationError):
            dedupe_latest([a, b])

    def test_doubleheader_gamepk_identity_never_collides(self):
        a = quote(pk=777)
        b = quote(pk=778)
        out = dedupe_latest([a, b])
        self.assertEqual(len(out), 2)
        self.assertNotEqual(out[0].sportsedge_game_id, out[1].sportsedge_game_id)


if __name__ == "__main__":
    unittest.main()
