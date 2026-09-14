import unittest

from scripts.capture_nfl_market_maker_radar import (
    NFLRadarCaptureError,
    bind_events,
    build_observation_rows,
    canonical_team_id,
)
from scripts.analyze_market_maker_radar import analyze, load_policy


def _pin(start="2026-09-20T17:00:00Z"):
    return {
        "book": "pinnacle",
        "provider_event_id": 100,
        "away_team": "Pittsburgh Steelers",
        "home_team": "New England Patriots",
        "commence_time": start,
        "raw_sha256": "p" * 64,
        "quotes": [
            {"market": "h2h", "designation": "home", "point": None, "american_price": -120},
            {"market": "h2h", "designation": "away", "point": None, "american_price": 110},
            {"market": "spreads", "designation": "home", "point": -2.5, "american_price": -105},
            {"market": "spreads", "designation": "away", "point": 2.5, "american_price": -107},
            {"market": "totals", "designation": "over", "point": 42.0, "american_price": -110},
            {"market": "totals", "designation": "under", "point": 42.0, "american_price": -106},
        ],
    }


def _fd(start="2026-09-20T17:01:00Z", event_id=200):
    return {
        "book": "fanduel",
        "provider_event_id": event_id,
        "away_team": "Pittsburgh Steelers",
        "home_team": "New England Patriots",
        "commence_time": start,
        "raw_sha256": "f" * 64,
        "quotes": [
            {"market": "h2h", "designation": "home", "point": None, "american_price": -118},
            {"market": "h2h", "designation": "away", "point": None, "american_price": 108},
            {"market": "spreads", "designation": "home", "point": -2.5, "american_price": -102},
            {"market": "spreads", "designation": "away", "point": 2.5, "american_price": -110},
            {"market": "totals", "designation": "over", "point": 42.0, "american_price": -108},
            {"market": "totals", "designation": "under", "point": 42.0, "american_price": -108},
        ],
    }


def _dk(start="2026-09-20T17:00:00Z", event_id="300"):
    return {
        "book": "draftkings",
        "provider_event_id": event_id,
        "away_team": "Pittsburgh Steelers",
        "home_team": "New England Patriots",
        "commence_time": start,
        "raw_sha256": "d" * 64,
        "quotes": [
            {"market": "h2h", "outcome": "New England Patriots", "point": None, "price_american": -115},
            {"market": "h2h", "outcome": "Pittsburgh Steelers", "point": None, "price_american": 105},
            {"market": "spreads", "outcome": "New England Patriots", "point": -2.5, "price_american": -104},
            {"market": "spreads", "outcome": "Pittsburgh Steelers", "point": 2.5, "price_american": -108},
            {"market": "totals", "outcome": "Over", "point": 42.0, "price_american": -105},
            {"market": "totals", "outcome": "Under", "point": 42.0, "price_american": -110},
        ],
    }


class NFLDirectRadarCaptureTests(unittest.TestCase):
    def test_team_identity_uses_strict_unique_nfl_mascot(self):
        self.assertEqual(canonical_team_id("New England Patriots"), "patriots")
        self.assertEqual(canonical_team_id("NY Jets"), "jets")
        self.assertEqual(canonical_team_id("San Francisco 49ers"), "49ers")
        with self.assertRaisesRegex(NFLRadarCaptureError, "TEAM_UNRECOGNIZED"):
            canonical_team_id("New England")

    def test_one_minute_provider_start_skew_binds_same_event(self):
        bound, coverage = bind_events(pinnacle=[_pin()], draftkings=[_dk()], fanduel=[_fd()])
        self.assertEqual(len(bound), 1)
        self.assertEqual(set(bound[0]["books"]), {"pinnacle", "draftkings", "fanduel"})
        self.assertEqual(coverage[0]["missing_books"], [])
        self.assertEqual(coverage[0]["ambiguous_books"], [])
        self.assertEqual(bound[0]["event_id"], "americanfootball_nfl:2026-09-20:steelers@patriots")

    def test_ambiguous_soft_match_is_not_silently_bound(self):
        bound, coverage = bind_events(
            pinnacle=[_pin()],
            draftkings=[_dk()],
            fanduel=[_fd(event_id=200), _fd(event_id=201)],
        )
        self.assertEqual(len(bound), 1)
        self.assertEqual(set(bound[0]["books"]), {"pinnacle", "draftkings"})
        self.assertEqual(coverage[0]["ambiguous_books"], ["fanduel"])

    def test_rows_share_poll_clock_and_canonical_outcomes(self):
        bound, _ = bind_events(pinnacle=[_pin()], draftkings=[_dk()], fanduel=[_fd()])
        rows = build_observation_rows(
            bound_events=bound,
            capture_id="poll-1",
            captured_at="2026-09-14T04:00:00Z",
        )
        self.assertEqual(len(rows), 18)
        self.assertEqual({row["capture_id"] for row in rows}, {"poll-1"})
        self.assertEqual({row["captured_at"] for row in rows}, {"2026-09-14T04:00:00Z"})
        self.assertTrue(all(row["book_last_update"] is None for row in rows))
        self.assertTrue(all(row["provider_quote_timestamp_available"] is False for row in rows))
        team_outcomes = {row["outcome"] for row in rows if row["market"] != "totals"}
        self.assertEqual(team_outcomes, {"patriots", "steelers"})

    def test_same_poll_book_changes_cannot_create_fake_leader(self):
        policy = load_policy()
        first_bound, _ = bind_events(pinnacle=[_pin()], draftkings=[_dk()], fanduel=[_fd()])
        first = build_observation_rows(
            bound_events=first_bound,
            capture_id="poll-1",
            captured_at="2026-09-14T04:00:00Z",
        )
        pin2 = _pin()
        dk2 = _dk()
        fd2 = _fd()
        for provider in (pin2, dk2, fd2):
            for quote in provider["quotes"]:
                if quote["market"] == "h2h" and (quote.get("designation") == "home" or quote.get("outcome") == "New England Patriots"):
                    if "american_price" in quote:
                        quote["american_price"] = -140
                    else:
                        quote["price_american"] = -140
        second_bound, _ = bind_events(pinnacle=[pin2], draftkings=[dk2], fanduel=[fd2])
        second = build_observation_rows(
            bound_events=second_bound,
            capture_id="poll-2",
            captured_at="2026-09-14T04:05:00Z",
        )
        report = analyze(first + second, policy)
        self.assertEqual(report["lead_lag_signal_count"], 0)
        self.assertGreaterEqual(report["synchronous_pair_count"], 2)
        self.assertEqual(report["model_p_authority"], False)
        self.assertEqual(report["staking_authority"], False)


if __name__ == "__main__":
    unittest.main()
