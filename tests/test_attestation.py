import unittest

from sportsedge.attestation import AttestationError, validate_attestation


HITS_FIXTURE = "8c15e196efa5fc7ef979d0a9cf5ec113cba54cd756482babc256c44d53642409"
TB_FIXTURE = "3abd596ae720529f5354f724c02c11e284a5044ac5842207599c27f4cb562e82"
CI_SHA = "a" * 40


def good_hits():
    return {
        "market": "HITS",
        "verdict": "PASS",
        "engine_version": "hits_engine_v1.2",
        "feature_version": "hits_batter_pitcher_pa_v1",
        "fixture_sha256": HITS_FIXTURE,
        "ci_commit_sha": CI_SHA,
        "test_name": "full_holdout_acceptance",
    }


def good_tb():
    return {
        "market": "TOTAL_BASES",
        "verdict": "PASS",
        "engine_version": "total_bases_engine_v0.2",
        "feature_version": "tb_event_rates_pitcher_park_pa_v1",
        "fixture_sha256": TB_FIXTURE,
        "ci_commit_sha": CI_SHA,
        "test_name": "full_holdout_acceptance",
    }


class AttestationTests(unittest.TestCase):
    def test_hits_requires_exact_fixture_engine_feature_test_and_ci_identity(self):
        out = validate_attestation(good_hits(), expected_ci_commit_sha=CI_SHA)
        self.assertTrue(out["eligible_for_promotion"])
        self.assertTrue(all(out["checks"].values()))

    def test_total_bases_requires_exact_resolved_fixture_identity(self):
        out = validate_attestation(good_tb(), expected_ci_commit_sha=CI_SHA)
        self.assertTrue(out["eligible_for_promotion"])
        bad = good_tb(); bad["fixture_sha256"] = "0" * 64
        rejected = validate_attestation(bad, expected_ci_commit_sha=CI_SHA)
        self.assertFalse(rejected["eligible_for_promotion"])
        self.assertFalse(rejected["checks"]["fixture_sha256"])

    def test_missing_expected_ci_commit_fails_closed(self):
        out = validate_attestation(good_hits())
        self.assertFalse(out["eligible_for_promotion"])
        self.assertFalse(out["checks"]["ci_commit_sha"])

    def test_wrong_or_malformed_ci_commit_fails_closed(self):
        for expected in ("b" * 40, "not-a-sha", "A" * 39):
            with self.subTest(expected=expected):
                out = validate_attestation(good_hits(), expected_ci_commit_sha=expected)
                self.assertFalse(out["eligible_for_promotion"])
                self.assertFalse(out["checks"]["ci_commit_sha"])

    def test_attested_ci_commit_must_be_hex_and_match_exact_commit(self):
        for attested in ("b" * 40, "z" * 40, "a" * 39):
            with self.subTest(attested=attested):
                candidate = good_hits(); candidate["ci_commit_sha"] = attested
                out = validate_attestation(candidate, expected_ci_commit_sha=CI_SHA)
                self.assertFalse(out["eligible_for_promotion"])
                self.assertFalse(out["checks"]["ci_commit_sha"])

    def test_fixture_feature_engine_and_test_identity_are_exact(self):
        mutations = {
            "fixture_sha256": "0" * 64,
            "feature_version": "hits_features_v1",
            "engine_version": "hits_engine_v1.1",
            "test_name": "some_other_test",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                candidate = good_hits(); candidate[field] = value
                out = validate_attestation(candidate, expected_ci_commit_sha=CI_SHA)
                self.assertFalse(out["eligible_for_promotion"])
                self.assertFalse(out["checks"][field])

    def test_unknown_market_fails_closed(self):
        with self.assertRaises(AttestationError):
            validate_attestation({"market": "FOO"}, expected_ci_commit_sha=CI_SHA)


if __name__ == "__main__":
    unittest.main()
