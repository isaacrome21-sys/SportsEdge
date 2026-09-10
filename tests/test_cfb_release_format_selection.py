from __future__ import annotations

import gzip
from hashlib import sha256
import unittest

from sportsedge.sports.cfb.historical_release import (
    CFBHistoricalReleaseError,
    select_release_asset,
)


def _asset(name: str, asset_id: int, raw: bytes) -> dict:
    packed = gzip.compress(raw) if name.endswith('.gz') else raw
    return {
        'id': asset_id,
        'name': name,
        'size': len(packed),
        'state': 'uploaded',
        'digest': 'sha256:' + sha256(packed).hexdigest(),
        'browser_download_url': (
            'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/'
            f'espn_cfb_schedules/{name}'
        ),
    }


def _release(assets: list[dict]) -> dict:
    return {
        'id': 101,
        'tag_name': 'espn_cfb_schedules',
        'updated_at': '2026-09-10T08:34:55Z',
        'draft': False,
        'prerelease': False,
        'assets': assets,
    }


class TestCFBReleaseFormatSelection(unittest.TestCase):
    def test_prefers_gzip_when_release_publishes_csv_and_gzip(self):
        csv_asset = _asset('cfb_schedule_2025.csv', 1, b'a,b\n1,2\n')
        gzip_asset = _asset('cfb_schedule_2025.csv.gz', 2, b'a,b\n1,2\n')
        selected = select_release_asset(
            _release([csv_asset, gzip_asset]), dataset='schedules', season=2025
        )
        self.assertEqual(selected.asset_name, 'cfb_schedule_2025.csv.gz')
        self.assertEqual(selected.asset_id, 2)

    def test_format_selection_is_independent_of_api_asset_order(self):
        csv_asset = _asset('cfb_schedule_2025.csv', 1, b'a,b\n1,2\n')
        gzip_asset = _asset('cfb_schedule_2025.csv.gz', 2, b'a,b\n1,2\n')
        first = select_release_asset(
            _release([csv_asset, gzip_asset]), dataset='schedules', season=2025
        )
        second = select_release_asset(
            _release([gzip_asset, csv_asset]), dataset='schedules', season=2025
        )
        self.assertEqual(first.asset_id, second.asset_id)
        self.assertEqual(first.sha256, second.sha256)

    def test_falls_back_to_csv_when_gzip_is_not_published(self):
        csv_asset = _asset('cfb_schedule_2025.csv', 1, b'a,b\n1,2\n')
        selected = select_release_asset(
            _release([csv_asset]), dataset='schedules', season=2025
        )
        self.assertEqual(selected.asset_name, 'cfb_schedule_2025.csv')

    def test_duplicate_preferred_representation_still_fails_closed(self):
        first = _asset('cfb_schedule_2025.csv.gz', 1, b'a,b\n1,2\n')
        second = dict(first, id=2)
        with self.assertRaisesRegex(CFBHistoricalReleaseError, 'ASSET_AMBIGUOUS'):
            select_release_asset(
                _release([first, second]), dataset='schedules', season=2025
            )


if __name__ == '__main__':
    unittest.main()
