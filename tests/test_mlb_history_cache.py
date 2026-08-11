import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from sportsedge.mlb_history_cache import MLBHistoryCachedOpener, MLBHistoryCacheError


class Resp:
    def __init__(self, value): self.raw = json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


class CountingOpener:
    def __init__(self): self.calls = []
    def __call__(self, req, timeout=15):
        url = req if isinstance(req, str) else req.full_url
        self.calls.append(url)
        return Resp({"stats": [{"splits": [{"url": url, "call": len(self.calls)}]}]})


class MLBHistoryCacheTests(unittest.TestCase):
    def test_same_history_url_reused_in_memory(self):
        base = CountingOpener()
        op = MLBHistoryCachedOpener(target_date=date(2026, 8, 11), opener=base)
        url = "https://statsapi.mlb.com/api/v1/people/100/stats?stats=gameLog&group=hitting&season=2026&gameType=R"
        with op(url) as r1: a = r1.read()
        with op(url) as r2: b = r2.read()
        self.assertEqual(a, b)
        self.assertEqual(len(base.calls), 1)

    def test_completed_season_disk_cache_reused_across_slate_dates(self):
        with tempfile.TemporaryDirectory() as td:
            url = "https://statsapi.mlb.com/api/v1/people/100/stats?stats=gameLog&group=hitting&season=2024&gameType=R"
            base1 = CountingOpener()
            op1 = MLBHistoryCachedOpener(target_date=date(2026, 8, 11), cache_dir=td, opener=base1)
            with op1(url) as r: expected = r.read()
            self.assertEqual(len(base1.calls), 1)
            base2 = CountingOpener()
            op2 = MLBHistoryCachedOpener(target_date=date(2026, 8, 12), cache_dir=td, opener=base2)
            with op2(url) as r: actual = r.read()
            self.assertEqual(actual, expected)
            self.assertEqual(base2.calls, [])

    def test_active_season_refetches_when_slate_date_advances(self):
        with tempfile.TemporaryDirectory() as td:
            url = "https://statsapi.mlb.com/api/v1/people/100/stats?stats=gameLog&group=hitting&season=2026&gameType=R"
            base = CountingOpener()
            with MLBHistoryCachedOpener(target_date=date(2026, 8, 11), cache_dir=td, opener=base)(url) as r: r.read()
            with MLBHistoryCachedOpener(target_date=date(2026, 8, 12), cache_dir=td, opener=base)(url) as r: r.read()
            self.assertEqual(len(base.calls), 2)

    def test_live_non_history_urls_are_never_cached(self):
        base = CountingOpener()
        op = MLBHistoryCachedOpener(target_date=date(2026, 8, 11), opener=base)
        url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-08-11"
        with op(url) as r: r.read()
        with op(url) as r: r.read()
        self.assertEqual(len(base.calls), 2)

    def test_corrupt_disk_cache_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = CountingOpener()
            op = MLBHistoryCachedOpener(target_date=date(2026, 8, 11), cache_dir=td, opener=base)
            url = "https://statsapi.mlb.com/api/v1/people/100/stats?stats=gameLog&group=hitting&season=2024&gameType=R"
            key = op._cache_key(url)
            path = Path(td) / f"{key}.json"
            path.write_text("not-json")
            with self.assertRaises(MLBHistoryCacheError) as cm:
                op(url)
            self.assertEqual(str(cm.exception), "HISTORY_CACHE_PAYLOAD_MALFORMED")
            self.assertEqual(base.calls, [])


if __name__ == "__main__":
    unittest.main()
