import unittest

from sportsedge.sports.nfl.source_manifest import build_nfl_source_manifest, manifest_sha256


class NFLSourceManifestTests(unittest.TestCase):
    def test_manifest_hash_is_canonical_and_order_independent(self):
        left = build_nfl_source_manifest([
            {"name": "schedule", "uri": "u1", "sha256": "a" * 64},
            {"name": "pbp_2024", "uri": "u2", "sha256": "b" * 64},
        ], schedule_anchor_sha256="a" * 64)
        right = build_nfl_source_manifest([
            {"sha256": "b" * 64, "uri": "u2", "name": "pbp_2024"},
            {"sha256": "a" * 64, "name": "schedule", "uri": "u1"},
        ], schedule_anchor_sha256="a" * 64)
        self.assertEqual(manifest_sha256(left), manifest_sha256(right))

    def test_duplicate_source_name_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "NFL_SOURCE_NAME_DUPLICATE"):
            build_nfl_source_manifest([
                {"name": "schedule", "uri": "u1", "sha256": "a" * 64},
                {"name": "schedule", "uri": "u2", "sha256": "b" * 64},
            ], schedule_anchor_sha256="a" * 64)

    def test_schedule_anchor_must_match_schedule_entry(self):
        with self.assertRaisesRegex(ValueError, "NFL_SOURCE_SCHEDULE_ANCHOR_MISMATCH"):
            build_nfl_source_manifest([
                {"name": "schedule", "uri": "u1", "sha256": "b" * 64},
            ], schedule_anchor_sha256="a" * 64)

    def test_changing_any_source_hash_changes_manifest_hash(self):
        first = build_nfl_source_manifest([
            {"name": "schedule", "uri": "u1", "sha256": "a" * 64},
            {"name": "stadiums", "uri": "u2", "sha256": "b" * 64},
        ], schedule_anchor_sha256="a" * 64)
        second = build_nfl_source_manifest([
            {"name": "schedule", "uri": "u1", "sha256": "a" * 64},
            {"name": "stadiums", "uri": "u2", "sha256": "c" * 64},
        ], schedule_anchor_sha256="a" * 64)
        self.assertNotEqual(manifest_sha256(first), manifest_sha256(second))


if __name__ == "__main__": unittest.main()
