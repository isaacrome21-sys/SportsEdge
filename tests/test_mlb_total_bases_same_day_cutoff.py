import json
import unittest
from datetime import date, datetime, timezone

from sportsedge.mlb_total_bases_features import (
    LG, LG_PH, PITCHER_SHRINK, SH, MLBTBHistorySource,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)
TARGET = date(2026, 8, 11)
BATTER, STARTER, VENUE = 10, 20, 3313


class Resp:
    def __init__(self, obj):
        self.raw = json.dumps(obj).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


def payload(rows):
    return {"stats": [{"splits": rows}]}


def hit_row(day, pk, singles, doubles, triples, hr, pa):
    hits = singles + doubles + triples + hr
    stat = {"hits": hits, "doubles": doubles, "triples": triples,
            "homeRuns": hr, "plateAppearances": pa}
    return {"date": day, "game": {"gamePk": pk}, "stat": stat}


def field_row(day, pk, started):
    return {"date": day, "game": {"gamePk": pk}, "stat": {"gamesStarted": started}}


def pitch_row(day, pk, hits, hr, bfp, started):
    return {"date": day, "game": {"gamePk": pk},
            "stat": {"hits": hits, "homeRuns": hr, "battersFaced": bfp, "gamesStarted": started}}


class SameDayCutoffTests(unittest.TestCase):
    """The TB builder must exclude the target date and later games.

    Existing tests stub batter_prior_state / starter_prior_state, so the
    date filter in the real code path was never exercised. These fixtures
    put a loud same-day and a future-dated row into the real fetch path.
    If the `d >= target_date` filters are removed, these tests fail.
    """

    def setUp(self):
        # Batter: 12 prior started games, 10 PA each, all singles.
        self.hitting = [hit_row(f"2026-04-{i:02d}", 1000 + i, 1, 0, 0, 0, 10) for i in range(1, 13)]
        self.hitting += [
            hit_row("2026-08-11", 9999, 2, 1, 0, 1, 5),   # same-day: must be excluded
            hit_row("2026-08-12", 9998, 3, 0, 1, 0, 6),   # future: must be excluded
        ]
        self.fielding = [field_row(f"2026-04-{i:02d}", 1000 + i, 1) for i in range(1, 13)]
        self.fielding += [
            field_row("2026-08-11", 9999, 1),
            field_row("2026-08-12", 9998, 1),
        ]
        # Starter: 6 prior starts (18 H, 6 HR, 120 BFP), one relief app, and a same-day start.
        self.pitching = [pitch_row(f"2026-04-{i:02d}", 2000 + i, 3, 1, 20, 1) for i in range(1, 7)]
        self.pitching += [
            pitch_row("2026-04-07", 2007, 2, 0, 10, 0),   # relief: gamesStarted 0, excluded
            pitch_row("2026-08-11", 9997, 20, 5, 30, 1),  # same-day start: must be excluded
        ]

    def opener(self, url, timeout=15):
        in_target_season = "season=2026" in url
        if in_target_season:
            if f"/people/{BATTER}/stats?" in url and "group=hitting" in url:
                return Resp(payload(self.hitting))
            if f"/people/{BATTER}/stats?" in url and "group=fielding" in url:
                return Resp(payload(self.fielding))
            if f"/people/{STARTER}/stats?" in url and "group=pitching" in url:
                return Resp(payload(self.pitching))
        if "/people/" in url and any(f"season={y}" in url for y in range(2021, 2026)):
            return Resp(payload([]))
        raise AssertionError(f"unexpected fetch: {url}")

    def source(self):
        return MLBTBHistorySource(opener=self.opener, retrieved_at=NOW)

    def test_same_day_and_future_games_do_not_enter_features(self):
        values, latest, site = self.source().build_values(
            target_date=TARGET, batter_id=BATTER, starter_id=STARTER, venue_id=VENUE,
        )
        # Batter: 12 prior singles over 120 PA. Same-day and future rows excluded.
        for k, expected_num in (("s", 12), ("d", 0), ("t", 0), ("hr", 0)):
            self.assertAlmostEqual(
                values["rates"][k], (expected_num + LG[k] * SH) / (120 + SH), places=15,
            )
        self.assertEqual(values["pa_pool"], [10] * 12)

        # Starter: 6 prior starts only (18 H, 6 HR, 120 BFP). Relief and same-day excluded.
        self.assertAlmostEqual(
            values["p_h"], (18 + LG_PH * PITCHER_SHRINK) / (120 + PITCHER_SHRINK), places=15,
        )
        self.assertAlmostEqual(
            values["p_hr"], (6 + LG["hr"] * PITCHER_SHRINK) / (120 + PITCHER_SHRINK), places=15,
        )
        self.assertEqual(site, "NYC21")
        # Latest prior-game date is the last pre-target game, never the target date.
        self.assertEqual(latest, date(2026, 4, 12))
        self.assertLess(latest, TARGET)

    def test_same_day_start_is_not_counted_in_start_pool(self):
        src = self.source()
        starts = src._started_games(BATTER, TARGET)
        self.assertNotIn(9999, starts)
        self.assertNotIn(9998, starts)
        self.assertEqual(len(starts), 12)


if __name__ == "__main__":
    unittest.main()
