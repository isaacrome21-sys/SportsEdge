from __future__ import annotations

import csv
import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_cfb_historical_market_archive import (
    _git_blob_sha1,
    _load_contract,
    _profile_archive,
    _validate_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/research/cfb_historical_market_source_v1.json"
ADOPTIONS = ROOT / "config/cfb_external_repo_adoptions_v1.json"


class CFBHistoricalMarketSourceTests(unittest.TestCase):
    def _fixture_bytes(self) -> bytes:
        columns = [
            "id",
            "game_id",
            "season",
            "game_desc",
            "date_time",
            "market_type",
            "abbr",
            "lines",
            "odds",
            "opening_lines",
            "opening_odds",
            "book",
            "season_type",
            "week",
            "home_team_id",
            "away_team_id",
        ]
        rows = [
            ["1", "100", "2006", "A@B", "2006-09-01", "spread", "B", "-3", "", "-2.5", "", "Book A", "regular", "1", "2", "1"],
            ["2", "200", "2025", "C@D", "2025-09-01", "money_line", "D", "", "-120", "", "", "Book B", "regular", "1", "4", "3"],
        ]
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerow(columns)
        writer.writerows(rows)
        return gzip.compress(text.getvalue().encode("utf-8"), mtime=0)

    def _fixture_contract(self, data: bytes) -> dict:
        checked = json.loads(CONTRACT.read_text(encoding="utf-8"))
        checked["upstream"] = dict(checked["upstream"])
        checked["upstream"]["expected_size_bytes"] = len(data)
        checked["upstream"]["git_blob_sha1"] = _git_blob_sha1(data)
        checked["upstream"]["expected_sha256"] = None
        checked["documented_history"] = dict(checked["documented_history"])
        checked["documented_history"]["documented_row_count"] = 2
        checked["documented_history"]["season_start"] = 2006
        checked["documented_history"]["season_end"] = 2025
        return checked

    def test_checked_contract_pins_exact_upstream_identity_and_zero_authority(self):
        contract = _load_contract(CONTRACT)
        upstream = contract["upstream"]
        self.assertEqual(upstream["repository"], "sportsdataverse/cfbfastR-data")
        self.assertEqual(upstream["commit"], "f5a05dc815951b8dbe18961a824f34cf154dfa61")
        self.assertEqual(upstream["path"], "betting/csv/cfb_line_odds.csv.gz")
        self.assertEqual(upstream["git_blob_sha1"], "fe568cf1ef50794c80fdbbbff6a8e1061f76528e")
        self.assertEqual(upstream["expected_size_bytes"], 7047701)
        self.assertIsNone(upstream["expected_sha256"])
        self.assertEqual(contract["mode"], "RESEARCH_ONLY")
        self.assertIs(contract["evidence_limitations"]["per_row_pit_certified"], False)
        self.assertIs(contract["evidence_limitations"]["clv_authority"], False)
        for field in (
            "model_p_authority",
            "truth_gate_authority",
            "promotion_authority",
            "staking_authority",
            "official_bet_authority",
        ):
            self.assertIs(contract["authority"][field], False)

    def test_existing_external_repo_policy_remains_reference_only_and_non_authoritative(self):
        policy = json.loads(ADOPTIONS.read_text(encoding="utf-8"))
        self.assertEqual(policy["status"], "RESEARCH_AND_ENGINEERING_REFERENCE_ONLY")
        authority = policy["authority"]
        for field in (
            "predictive_model_input",
            "model_p_authority",
            "truth_gate_input",
            "promotion_authority",
            "eligibility_authority",
            "edge_floor_authority",
            "official_authority",
        ):
            self.assertIs(authority[field], False)
        governance = policy["governance"]
        for field in (
            "may_create_model_p",
            "may_satisfy_pit_source_manifest",
            "may_satisfy_asof_availability_proof",
            "may_satisfy_paired_market_evidence",
            "may_change_market_eligibility",
        ):
            self.assertIs(governance[field], False)

    def test_bootstrap_accepts_exact_git_blob_but_normal_mode_requires_sha256(self):
        data = self._fixture_bytes()
        contract = self._fixture_contract(data)
        observed = _validate_bytes(data, contract, allow_bootstrap_sha256=True)
        self.assertEqual(observed["git_blob_sha1"], _git_blob_sha1(data))
        self.assertEqual(observed["size_bytes"], len(data))
        self.assertEqual(len(observed["sha256"]), 64)
        with self.assertRaisesRegex(ValueError, "SHA256_UNPINNED"):
            _validate_bytes(data, contract, allow_bootstrap_sha256=False)

    def test_pinned_sha256_and_tamper_are_fail_closed(self):
        data = self._fixture_bytes()
        contract = self._fixture_contract(data)
        observed = _validate_bytes(data, contract, allow_bootstrap_sha256=True)
        contract["upstream"]["expected_sha256"] = observed["sha256"]
        self.assertEqual(
            _validate_bytes(data, contract, allow_bootstrap_sha256=False)["sha256"],
            observed["sha256"],
        )
        tampered = data[:-1] + bytes([data[-1] ^ 1])
        with self.assertRaises(ValueError):
            _validate_bytes(tampered, contract, allow_bootstrap_sha256=False)

    def test_streaming_profile_enforces_schema_rows_and_season_range(self):
        data = self._fixture_bytes()
        contract = self._fixture_contract(data)
        profile = _profile_archive(data, contract)
        self.assertEqual(profile["row_count"], 2)
        self.assertEqual(profile["season_min"], 2006)
        self.assertEqual(profile["season_max"], 2025)
        self.assertEqual(profile["market_type_counts"], {"money_line": 1, "spread": 1})
        self.assertEqual(profile["book_count"], 2)
        self.assertEqual(profile["null_counts"]["lines"], 1)
        self.assertEqual(profile["null_counts"]["odds"], 1)

    def test_missing_required_column_fails(self):
        data = gzip.compress(b"season,book\n2006,Book A\n", mtime=0)
        contract = self._fixture_contract(data)
        contract["documented_history"]["documented_row_count"] = 1
        with self.assertRaisesRegex(ValueError, "COLUMNS_MISSING"):
            _profile_archive(data, contract)

    def test_invalid_authority_contract_is_rejected(self):
        payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
        payload["authority"]["model_p_authority"] = True
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "contract.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "FORBIDDEN_AUTHORITY"):
                _load_contract(path)


if __name__ == "__main__":
    unittest.main()
