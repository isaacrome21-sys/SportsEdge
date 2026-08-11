import json
import unittest
from datetime import date, datetime, timezone

from sportsedge.feature_bridge import resolve_feature_row
from sportsedge.mlb_hits_features import (
    BATTER_SHRINK, LEAGUE_HIT, LEAGUE_P_H, PITCHER_SHRINK,
    MLBHitsFeatureError, MLBHitsHistorySource,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)


class Resp:
    def __init__(self, obj): self.raw = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


def payload(rows):
    return {"stats": [{"splits": rows}]}


def hrow(day, pk, hits, pa):
    return {"date": day, "game": {"gamePk": pk}, "stat": {"hits": hits, "plateAppearances": pa}}


def frow(day, pk, started, position="1B"):
    return {
        "date": day, "game": {"gamePk": pk}, "position": {"abbreviation": position},
        "stat": {"gamesStarted": started, "innings": "0.0" if position == "DH" else "9.0"},
    }


def prow(day, pk, hits, bfp, started):
    return {"date": day, "game": {"gamePk": pk}, "stat": {"hits": hits, "battersFaced": bfp, "gamesStarted": started}}


class MLBHitsFeatureTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.hitting = [
            hrow("2026-04-01", 101, 1, 4),
            hrow("2026-04-02", 102, 0, 1),  # pinch-hit appearance: counts in b_rate only
            hrow("2026-04-03", 103, 2, 5),
            hrow("2026-04-04", 104, 1, 4),
            hrow("2026-04-05", 105, 0, 4),
            hrow("2026-04-06", 106, 1, 3),
            hrow("2026-08-11", 107, 4, 5),  # same-date game must never enter pregame features
        ]
        self.fielding = [
            frow("2026-04-01", 101, 1),
            frow("2026-04-02", 102, 0),
            frow("2026-04-03", 103, 1, "DH"),
            frow("2026-04-04", 104, 1),
            frow("2026-04-05", 105, 1),
            frow("2026-04-06", 106, 1),
            frow("2026-08-11", 107, 1),
        ]
        self.pitching = [
            prow("2026-03-30", 201, 5, 25, 1),
            prow("2026-04-05", 202, 2, 7, 0),  # relief: excluded
            prow("2026-04-10", 203, 7, 30, 1),
            prow("2026-08-11", 204, 20, 30, 1),  # same-date: excluded
        ]

    def opener(self, url, timeout=15):
        self.calls.append(url)
        if "/people/10/stats?" in url and "group=hitting" in url and "season=2026" in url: return Resp(payload(self.hitting))
        if "/people/10/stats?" in url and "group=fielding" in url and "season=2026" in url: return Resp(payload(self.fielding))
        if "/people/20/stats?" in url and "group=pitching" in url and "season=2026" in url: return Resp(payload(self.pitching))
        # 2021-2025 are valid empty seasons under the frozen history contract.
        if "/people/" in url and any(f"season={y}" in url for y in range(2021, 2026)): return Resp(payload([]))
        raise AssertionError(url)

    def source(self):
        return MLBHitsHistorySource(opener=self.opener, retrieved_at=NOW)

    def test_exact_formula_start_pool_and_same_day_exclusion(self):
        src = self.source()
        b_rate, p_rate, pa_pool, latest = src.build_values(target_date=date(2026, 8, 11), batter_id=10, starter_id=20)
        # Six prior hitting games, including the pinch-hit PA; same-day row excluded.
        bh, bpa = 5, 21
        self.assertAlmostEqual(b_rate, (bh + LEAGUE_HIT * BATTER_SHRINK) / (bpa + BATTER_SHRINK), places=15)
        # Only the two prior pitching starts count.
        self.assertAlmostEqual(p_rate, (12 + LEAGUE_P_H * PITCHER_SHRINK) / (55 + PITCHER_SHRINK), places=15)
        self.assertEqual(pa_pool, [4, 5, 4, 4, 3])
        self.assertEqual(latest, date(2026, 4, 10))

    def test_dh_start_is_counted_and_nonstart_pa_is_not(self):
        src = self.source()
        hitting = src.hitting_history(10, date(2026, 8, 11))
        starts = src.started_games(10, date(2026, 8, 11))
        self.assertIn(103, starts)  # DH with innings=0 and gamesStarted=1
        self.assertNotIn(102, starts)
        self.assertEqual([x.pa for x in hitting if x.game_pk in starts], [4, 5, 4, 4, 3])

    def test_run_scoped_cache_prevents_refetch(self):
        src = self.source()
        src.hitting_history(10, date(2026, 8, 11))
        first = len(self.calls)
        src.hitting_history(10, date(2026, 8, 11))
        self.assertEqual(len(self.calls), first)

    def test_feature_envelope_resolves_through_shared_bridge(self):
        src = self.source()
        env = src.feature_envelope(game_pk=777, team_id=1, target_date=date(2026, 8, 11), batter_id=10, starter_id=20)
        row = resolve_feature_row(
            market="HITS", game_pk=777, player_id=10, team_id=1,
            feature_fact_keys=env["feature_fact_keys"], sources=env["sources"], ttl_by_feature=env["ttl_by_feature"],
            now=NOW, wager_cutoff=datetime(2026, 8, 11, 23, 0, tzinfo=UTC),
        )
        self.assertEqual(row["pa_pool"], [4, 5, 4, 4, 3])
        self.assertEqual(row["feature_version"], "hits_batter_pitcher_pa_v1")
        self.assertTrue(row["provenance"])

    def test_too_few_true_starts_fails_closed(self):
        self.fielding = self.fielding[:4]
        with self.assertRaises(MLBHitsFeatureError) as ctx:
            self.source().build_values(target_date=date(2026, 8, 11), batter_id=10, starter_id=20)
        self.assertEqual(ctx.exception.reason, "MLB_BATTER_START_SAMPLE_TOO_SMALL")

    def test_zero_starter_bfp_fails_closed(self):
        self.pitching = [prow("2026-04-01", 201, 0, 0, 1)]
        with self.assertRaises(MLBHitsFeatureError) as ctx:
            self.source().build_values(target_date=date(2026, 8, 11), batter_id=10, starter_id=20)
        self.assertEqual(ctx.exception.reason, "MLB_STARTER_BFP_HISTORY_MISSING")

    def test_malformed_stat_is_not_clipped_or_guessed(self):
        self.hitting[0] = hrow("2026-04-01", 101, 5, 4)
        with self.assertRaises(MLBHitsFeatureError) as ctx:
            self.source().build_values(target_date=date(2026, 8, 11), batter_id=10, starter_id=20)
        self.assertEqual(ctx.exception.reason, "MLB_FEATURE_MALFORMED")


if __name__ == "__main__": unittest.main()
