from __future__ import annotations

import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb import history_cache as hc
from sportsedge.sports.cfb.market_archive import iter_market_archive
from sportsedge.sports.cfb.historical_release import CFBHistoricalReleaseError


class FakeResponse(io.BytesIO):
    pass


class FakeOpener:
    def __init__(self, dataset="adv_team"):
        self.dataset = dataset
        self.raw = b"team,epa\nAlpha,0.1\n"
        self.asset_calls = 0
        self.meta_calls = 0

    def __call__(self, request, timeout=60):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/releases/tags/" in url:
            self.meta_calls += 1
            tag = hc.release_api_url(self.dataset).rsplit("/", 1)[-1]
            prefix = {
                "schedules": "cfb_schedule",
                "adv_team": "adv_team",
                "adv_situational": "adv_situational",
                "adv_drives": "adv_drives",
                "play_by_play": "play_by_play",
                "betting": "betting",
            }[self.dataset]
            name = f"{prefix}_2024.csv"
            asset_url = (
                "https://github.com/sportsdataverse/sportsdataverse-data/"
                f"releases/download/{tag}/{name}"
            )
            payload = {
                "id": 10,
                "tag_name": tag,
                "updated_at": "2026-08-03T03:00:54Z",
                "draft": False,
                "prerelease": False,
                "assets": [{
                    "id": 11,
                    "name": name,
                    "size": len(self.raw),
                    "state": "uploaded",
                    "digest": "sha256:" + sha256(self.raw).hexdigest(),
                    "browser_download_url": asset_url,
                }],
            }
            return FakeResponse(json.dumps(payload).encode())
        if "/releases/download/" in url:
            self.asset_calls += 1
            return FakeResponse(self.raw)
        raise AssertionError(url)


class FakeArchiveOpener:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.calls = 0

    def __call__(self, request, timeout=60):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url != "https://example.invalid/cfb_line_odds.csv.gz":
            raise AssertionError(url)
        self.calls += 1
        return FakeResponse(self.raw)


def write_archive_contract(root: Path, raw: bytes) -> Path:
    path = root / "market_contract.json"
    payload = {
        "source_id": "CFB_HISTORICAL_MARKET_SOURCE_V1",
        "mode": "RESEARCH_ONLY",
        "status": "FROZEN_RESEARCH_SOURCE",
        "upstream": {
            "repository": "sportsdataverse/cfbfastR-data",
            "commit": "f5a05dc815951b8dbe18961a824f34cf154dfa61",
            "path": "betting/csv/cfb_line_odds.csv.gz",
            "raw_url": "https://example.invalid/cfb_line_odds.csv.gz",
            "expected_size_bytes": len(raw),
            "expected_sha256": sha256(raw).hexdigest(),
        },
        "verified_profile": {
            "row_count": 1,
            "season_start": 2024,
            "season_end": 2024,
        },
        "required_columns": ["game_id", "season", "market_type", "book"],
        "evidence_limitations": {
            "per_row_pit_certified": False,
            "decision_time_certified": False,
            "close_time_certified": False,
            "clv_authority": False,
        },
        "authority": {
            "model_p_authority": False,
            "truth_gate_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
            "official_bet_authority": False,
        },
    }
    canonical = json.loads((Path(__file__).resolve().parents[1] / "config/research/cfb_historical_market_source_v1.json").read_text())
    for key in ("schema_version", "sport", "restrictions", "restriction_sha256", "allowed_uses", "forbidden_uses", "authority", "evidence_limitations"):
        payload[key] = canonical[key]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class HistoryCacheTests(unittest.TestCase):
    def test_cache_verifies_writes_manifest_and_reuses_verified_file(self):
        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as tmp:
            first = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            self.assertEqual(first["row_count"], 1)
            self.assertFalse(first["cache_reused"])
            self.assertEqual(Path(first["cache_file"]).read_bytes(), opener.raw)
            manifest = json.loads(Path(first["manifest_file"]).read_text())
            self.assertEqual(manifest["content_sha256"], sha256(opener.raw).hexdigest())
            self.assertEqual(manifest["market_role"], "PREDICTIVE_INPUT")
            self.assertEqual(len(manifest["manifest_sha256"]), 64)
            self.assertEqual(opener.asset_calls, 1)

            second = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            self.assertTrue(second["cache_reused"])
            self.assertEqual(opener.asset_calls, 1)
            self.assertEqual(opener.meta_calls, 2)

    def test_corrupted_cache_is_replaced_from_verified_asset(self):
        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as tmp:
            first = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            Path(first["cache_file"]).write_bytes(b"corrupt")
            second = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            self.assertFalse(second["cache_reused"])
            self.assertEqual(Path(second["cache_file"]).read_bytes(), opener.raw)
            self.assertEqual(opener.asset_calls, 2)

    def test_betting_requires_explicit_benchmark_permission_before_network(self):
        opener = FakeOpener(dataset="betting")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CFBHistoricalReleaseError, "MARKET_DATA_PROHIBITED"):
                hc.cache_one(
                    dataset="betting", season=2024, cache_root=tmp, opener=opener
                )
            self.assertEqual(opener.meta_calls, 0)
            out = hc.cache_one(
                dataset="betting",
                season=2024,
                cache_root=tmp,
                opener=opener,
                allow_benchmark=True,
            )
            self.assertEqual(out["usage"], "BENCHMARK_ONLY")

    def test_multi_season_market_archive_requires_explicit_benchmark_permission(self):
        raw = gzip.compress(
            b"game_id,season,market_type,book\n1,2024,spread,Draft Kings\n",
            mtime=0,
        )
        opener = FakeArchiveOpener(raw)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = write_archive_contract(root, raw)
            with self.assertRaisesRegex(CFBHistoricalReleaseError, "MARKET_DATA_PROHIBITED"):
                hc.cache_market_archive(
                    contract_path=contract,
                    use="historical_market_coverage_profiling",
                    cache_root=root / "cache",
                    opener=opener,
                )
            self.assertEqual(opener.calls, 0)

    def test_multi_season_market_archive_cache_manifest_reuse_and_stream(self):
        raw = gzip.compress(
            b"game_id,season,market_type,book\n1,2024,spread,Draft Kings\n",
            mtime=0,
        )
        opener = FakeArchiveOpener(raw)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = write_archive_contract(root, raw)
            first = hc.cache_market_archive(
                contract_path=contract,
                    use="historical_market_coverage_profiling",
                cache_root=root / "cache",
                allow_benchmark=True,
                opener=opener,
            )
            self.assertEqual(first["usage"], "BENCHMARK_ONLY")
            self.assertFalse(first["cache_reused"])
            self.assertEqual(first["row_count"], 1)
            manifest = json.loads(Path(first["manifest_file"]).read_text())
            self.assertEqual(manifest["usage"], "BENCHMARK_ONLY")
            self.assertIs(manifest["pit_certified"], False)
            self.assertIs(manifest["clv_authority"], False)
            self.assertIs(manifest["promotion_authority"], False)
            self.assertEqual(manifest["content_sha256"], sha256(raw).hexdigest())
            self.assertEqual(len(manifest["manifest_sha256"]), 64)
            rows = list(
                iter_market_archive(
                    contract_path=contract,
                    use="historical_market_coverage_profiling",
                    cache_file=first["cache_file"],
                )
            )
            self.assertEqual(rows, [{"game_id": "1", "season": "2024", "market_type": "spread", "book": "Draft Kings"}])

            second = hc.cache_market_archive(
                contract_path=contract,
                    use="historical_market_coverage_profiling",
                cache_root=root / "cache",
                allow_benchmark=True,
                opener=opener,
            )
            self.assertTrue(second["cache_reused"])
            self.assertEqual(opener.calls, 1)

    def test_multi_season_corrupt_cache_is_replaced_and_bad_download_not_exposed(self):
        raw = gzip.compress(
            b"game_id,season,market_type,book\n1,2024,total,Pinnacle\n",
            mtime=0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = write_archive_contract(root, raw)
            opener = FakeArchiveOpener(raw)
            first = hc.cache_market_archive(
                contract_path=contract,
                    use="historical_market_coverage_profiling",
                cache_root=root / "cache",
                allow_benchmark=True,
                opener=opener,
            )
            Path(first["cache_file"]).write_bytes(b"corrupt")
            second = hc.cache_market_archive(
                contract_path=contract,
                    use="historical_market_coverage_profiling",
                cache_root=root / "cache",
                allow_benchmark=True,
                opener=opener,
            )
            self.assertFalse(second["cache_reused"])
            self.assertEqual(opener.calls, 2)

            bad_root = root / "bad"
            bad = FakeArchiveOpener(raw + b"tamper")
            with self.assertRaises(hc.CFBHistoryCacheError):
                hc.cache_market_archive(
                    contract_path=contract,
                    use="historical_market_coverage_profiling",
                    cache_root=bad_root,
                    allow_benchmark=True,
                    opener=bad,
                )
            target = bad_root / "betting_archive" / json.loads(contract.read_text())["restriction_sha256"] / sha256(raw).hexdigest() / "cfb_line_odds.csv.gz"
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_season_ranges_and_predictive_expansion_are_deterministic(self):
        self.assertEqual(
            hc.parse_season_spec(["2022:2024", "2024,2025"]),
            (2022, 2023, 2024, 2025),
        )
        names = hc.resolve_datasets(["predictive"])
        self.assertIn("play_by_play", names)
        self.assertNotIn("betting", names)


if __name__ == "__main__":
    unittest.main()
