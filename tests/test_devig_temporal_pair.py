from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.devig import DevigError, validate_pair_temporal


NOW = datetime(2026, 8, 29, 13, 0, tzinfo=timezone.utc)


def quote(side, seconds_old):
    return {
        "game_id": "g1",
        "period": "FG",
        "market": "TOTALS",
        "entity_id": "g1",
        "book_key": "draftkings",
        "is_alternate": False,
        "line": 8.5,
        "side": side,
        "american_odds": -110,
        "retrieved_at": NOW - timedelta(seconds=seconds_old),
    }


class TemporalPairTests(unittest.TestCase):
    def test_fresh_synchronized_pair_passes(self):
        validate_pair_temporal(quote("OVER", 10), quote("UNDER", 20), cutoff=NOW, max_age_seconds=180, max_skew_seconds=30)

    def test_pair_skew_fails(self):
        with self.assertRaisesRegex(DevigError, "TIMESTAMP_SKEW"):
            validate_pair_temporal(quote("OVER", 10), quote("UNDER", 50), cutoff=NOW, max_age_seconds=180, max_skew_seconds=30)

    def test_stale_pair_fails(self):
        with self.assertRaisesRegex(DevigError, "STALE"):
            validate_pair_temporal(quote("OVER", 181), quote("UNDER", 170), cutoff=NOW, max_age_seconds=180, max_skew_seconds=30)

    def test_future_pair_fails(self):
        future = quote("OVER", -1)
        with self.assertRaisesRegex(DevigError, "FROM_FUTURE"):
            validate_pair_temporal(future, quote("UNDER", 1), cutoff=NOW, max_age_seconds=180, max_skew_seconds=30)


if __name__ == "__main__":
    unittest.main()
