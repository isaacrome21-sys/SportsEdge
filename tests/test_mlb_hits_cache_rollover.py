import json
import tempfile
import unittest
from datetime import date
from urllib.parse import parse_qs, urlparse

from sportsedge.mlb_hits_features import JsonHistoryCache, _game_logs


class Resp:
    def __init__(self, obj): self.raw = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


class HitsCacheRolloverTests(unittest.TestCase):
    def test_historical_seasons_reuse_cache_but_active_season_rotates_daily(self):
        calls = []
        def opener(req, timeout=15):
            url = req if isinstance(req, str) else req.full_url
            calls.append(url)
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            self.assertEqual(qs["group"], ["hitting"])
            return Resp({"stats": [{"splits": []}]})

        with tempfile.TemporaryDirectory() as tmp:
            cache = JsonHistoryCache(tmp)
            _game_logs(100, "hitting", through=date(2026, 8, 11), opener=opener, cache=cache)
            first = len(calls)
            self.assertEqual(first, 6)  # 2021..2026

            _game_logs(100, "hitting", through=date(2026, 8, 11), opener=opener, cache=cache)
            self.assertEqual(len(calls), first)  # same slate date: all cached

            _game_logs(100, "hitting", through=date(2026, 8, 12), opener=opener, cache=cache)
            # Frozen seasons 2021..2025 reuse cache; mutable 2026 gets one fresh fetch.
            self.assertEqual(len(calls), first + 1)


if __name__ == "__main__": unittest.main()
