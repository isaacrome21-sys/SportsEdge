import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path

from sportsedge.fixture_io import FixtureIOError, read_canonical_fixture_bytes


class FixtureIOTests(unittest.TestCase):
    def test_raw_and_gzip_transport_resolve_to_same_canonical_bytes(self):
        canonical = b"sportsedge-fixture\x00payload" * 100
        digest = hashlib.sha256(canonical).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "fixture.pkl"
            gz = Path(td) / "fixture.pkl.gz"
            raw.write_bytes(canonical)
            gz.write_bytes(gzip.compress(canonical, mtime=0))
            self.assertEqual(read_canonical_fixture_bytes(raw, expected_sha256=digest), canonical)
            self.assertEqual(read_canonical_fixture_bytes(gz, expected_sha256=digest), canonical)

    def test_wrong_canonical_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fixture.pkl"
            p.write_bytes(b"real bytes")
            with self.assertRaisesRegex(FixtureIOError, "fixture hash mismatch"):
                read_canonical_fixture_bytes(p, expected_sha256="0" * 64)

    def test_corrupt_gzip_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fixture.pkl.gz"
            p.write_bytes(b"\x1f\x8bnot-valid-gzip")
            with self.assertRaisesRegex(FixtureIOError, "invalid gzip fixture transport"):
                read_canonical_fixture_bytes(p, expected_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
