import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sportsedge.mlb_hits_features import (
    JsonHistoryCache,
    LEAGUE_HIT,
    LEAGUE_PH,
    MLBHitsFeatureError,
    SH_B,
    SH_P,
    build_hits_feature_envelope,
    build_live_hits_features,
)

UTC = timezone.utc
BATTER = 100
STARTER = 200
GAME_DATE = "2026-08-11"


class Resp:
    def __init__(self, obj): self.raw = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


def split(day, game_pk, stat):
    return {"date": day, "game": {"gamePk": game_pk}, "stat": stat}


def log_payload(rows):
    return {"stats": [{"splits": rows}]}


def boxscore(player_id, batting_order):
    return {"teams": {"away": {"players": {
        f"ID{player_id}": {"person": {"id": player_id}, "battingOrder": batting_order}
    }}, "home": {"players": {}}}}


class NativeHitsFeatureTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        # Five starts, one substitute, and one same-date game that must disappear.
        self.batting = [
            split("2026-08-01", 1, {"hits": 1, "plateAppearances": 4}),
            split("2026-08-02", 2, {"hits": 2, "plateAppearances": 5}),
            split("2026-08-03", 3, {"hits": 0, "plateAppearances": 4}),
            split("2026-08-04", 4, {"hits": 1, "plateAppearances": 4}),
            split("2026-08-05", 5, {"hits": 1, "plateAppearances": 5}),
            split("2026-08-06", 6, {"hits": 1, "plateAppearances": 2}), # substitute
            split("2026-08-11", 7, {"hits": 4, "plateAppearances": 4}), # same date: banned
        ]
        self.pitching = [
            split("2026-08-01", 21, {"gamesStarted": 1, "hits": 4, "battersFaced": 22}),
            split("2026-08-03", 22, {"gamesStarted": 0, "hits": 3, "battersFaced": 9}), # relief: ignored
            split("2026-08-07", 23, {"gamesStarted": 1, "hits": 5, "battersFaced": 25}),
            split("2026-08-11", 24, {"gamesStarted": 1, "hits": 10, "battersFaced": 30}), # same date: banned
        ]
        self.orders = {1: "100", 2: "200", 3: "300", 4: "400", 5: "500", 6: "101"}

    def opener(self, req, timeout=15):
        url = req if isinstance(req, str) else req.full_url
        self.calls.append(url)
        parsed = urlparse(url)
        if "/people/" in parsed.path and parsed.path.endswith("/stats"):
            qs = parse_qs(parsed.query)
            season = int(qs["season"][0])
            group = qs["group"][0]
            # Only 2026 carries rows; prior seasons intentionally empty.
            if season != 2026:
                return Resp(log_payload([]))
            return Resp(log_payload(self.batting if group == "hitting" else self.pitching))
        if "/game/" in parsed.path and parsed.path.endswith("/boxscore"):
            game_pk = int(parsed.path.split("/")[-2])
            return Resp(boxscore(BATTER, self.orders[game_pk]))
        raise AssertionError(url)

    def test_exact_formula_start_pool_and_same_date_cutoff(self):
        features, prov = build_live_hits_features(
            game_date=GAME_DATE, batter_id=BATTER, starter_id=STARTER, opener=self.opener
        )
        # cumulative hitting includes the substitute: H=6, PA=24; same-date row excluded
        expected_b = (6 + LEAGUE_HIT * SH_B) / (24 + SH_B)
        # pitching uses starts only: H=9, BFP=47; relief and same-date rows excluded
        expected_p = (9 + LEAGUE_PH * SH_P) / (47 + SH_P)
        self.assertEqual(features["pa_pool"], [4, 5, 4, 4, 5])
        self.assertEqual(features["b_rate"], expected_b)
        self.assertEqual(features["p_rate"], expected_p)
        self.assertEqual(prov["latest_batter_event_date"], "2026-08-06")
        self.assertEqual(prov["latest_starter_event_date"], "2026-08-07")

    def test_substitute_counts_rate_but_not_workload_pool(self):
        features, _ = build_live_hits_features(
            game_date=GAME_DATE, batter_id=BATTER, starter_id=STARTER, opener=self.opener
        )
        self.assertNotIn(2, features["pa_pool"])
        expected_without_sub = (5 + LEAGUE_HIT * SH_B) / (22 + SH_B)
        self.assertNotEqual(features["b_rate"], expected_without_sub)

    def test_insufficient_true_starts_fails_closed(self):
        self.orders[5] = "501"  # now only four true starts
        with self.assertRaisesRegex(MLBHitsFeatureError, "BATTER_PRIOR_STARTS_INSUFFICIENT"):
            build_live_hits_features(game_date=GAME_DATE, batter_id=BATTER, starter_id=STARTER, opener=self.opener)

    def test_missing_player_in_prior_boxscore_fails_closed(self):
        original = self.opener
        def op(req, timeout=15):
            url = req if isinstance(req, str) else req.full_url
            if "/game/3/boxscore" in url:
                return Resp({"teams": {"away": {"players": {}}, "home": {"players": {}}}})
            return original(req, timeout)
        with self.assertRaisesRegex(MLBHitsFeatureError, "PLAYER_NOT_IN_PRIOR_BOXSCORE"):
            build_live_hits_features(game_date=GAME_DATE, batter_id=BATTER, starter_id=STARTER, opener=op)

    def test_envelope_is_only_validated_contract_and_aware_provenance(self):
        env = build_hits_feature_envelope(
            game_pk=777, game_date=GAME_DATE, batter_id=BATTER, starter_id=STARTER,
            team_id=9, retrieved_at=datetime(2026, 8, 11, 15, 0, tzinfo=UTC), opener=self.opener,
        )
        self.assertEqual(set(env["feature_fact_keys"]), {"b_rate", "p_rate", "pa_pool"})
        self.assertEqual({x["fact_key"] for x in env["sources"]}, set(env["feature_fact_keys"].values()))
        self.assertNotIn("sportsbook", json.dumps(env).lower())
        self.assertTrue(all(x["retrieved_at"].endswith("+00:00") for x in env["sources"]))

    def test_cache_eliminates_repeat_network_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = JsonHistoryCache(tmp)
            first, _ = build_live_hits_features(
                game_date=GAME_DATE, batter_id=BATTER, starter_id=STARTER, opener=self.opener, cache=cache
            )
            first_count = len(self.calls)
            def forbidden(req, timeout=15):
                raise AssertionError("network should not be used after cache warm")
            second, _ = build_live_hits_features(
                game_date=GAME_DATE, batter_id=BATTER, starter_id=STARTER, opener=forbidden, cache=cache
            )
            self.assertEqual(first, second)
            self.assertGreater(first_count, 0)


if __name__ == "__main__":
    unittest.main()
