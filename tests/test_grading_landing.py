import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "landing", Path(__file__).resolve().parents[1] / "scripts/check_grading_landing.py")
landing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(landing)


class LandingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.request = {"schema_version": 1, "run_id": "2026-10-21-nightly",
                        "input_sha256": "a" * 64, "card_ids": ["nba-1"],
                        "no_cards": False}
        self.receipt = dict(self.request)
        self.receipt["report_path"] = "GRADE_AND_REVIEW.md"
        self.write_report()
        self.save()

    def write_report(self, binding=None, body="\n# Grade and review\n"):
        binding = binding or {k: self.request[k] for k in (
            "run_id", "input_sha256", "card_ids", "no_cards")}
        content = "<!-- grading-run " + json.dumps(binding, sort_keys=True) + " -->" + body
        self.report = self.root / "GRADE_AND_REVIEW.md"
        self.report.write_text(content)
        self.receipt["report_sha256"] = hashlib.sha256(self.report.read_bytes()).hexdigest()

    def save(self):
        for name, doc in (("request", self.request), ("receipt", self.receipt)):
            (self.root / (name + ".json")).write_text(json.dumps(doc))

    def check(self):
        self.save()
        return landing.check_landing(self.root / "request.json", self.root / "receipt.json")

    def test_matching_delivery_is_idempotent_read_only(self):
        before = self.report.read_bytes()
        self.assertEqual(self.check(), self.check())
        self.assertEqual(self.check()["status"], "LANDED")
        self.assertFalse(self.check()["grades_verified"])
        self.assertEqual(before, self.report.read_bytes())

    def test_missing_report_fails(self):
        self.report.unlink()
        with self.assertRaisesRegex(landing.LandingFailure, "REPORT_MISSING"):
            self.check()

    def test_empty_report_fails(self):
        self.report.write_text(" ")
        with self.assertRaisesRegex(landing.LandingFailure, "REPORT_EMPTY"):
            self.check()

    def test_altered_report_fails(self):
        self.report.write_text(self.report.read_text() + "changed")
        with self.assertRaisesRegex(landing.LandingFailure, "HASH_MISMATCH"):
            self.check()

    def test_yesterdays_receipt_cannot_satisfy_new_request(self):
        self.receipt["run_id"] = "yesterday"
        with self.assertRaisesRegex(landing.LandingFailure, "REQUEST_MISMATCH"):
            self.check()

    def test_new_receipt_cannot_relabel_old_report(self):
        old = {k: self.request[k] for k in ("run_id", "input_sha256", "card_ids", "no_cards")}
        old["run_id"] = "yesterday"
        self.write_report(binding=old)
        with self.assertRaisesRegex(landing.LandingFailure, "BINDING_MISMATCH"):
            self.check()

    def test_dropped_card_fails(self):
        self.request["card_ids"].append("nba-2")
        self.receipt["card_ids"] = ["nba-1"]
        with self.assertRaisesRegex(landing.LandingFailure, "REQUEST_MISMATCH"):
            self.check()

    def test_duplicate_card_fails(self):
        self.receipt["card_ids"] = ["nba-1", "nba-1"]
        with self.assertRaisesRegex(landing.LandingFailure, "DUPLICATE_CARD"):
            self.check()

    def test_valid_explicit_no_cards_delivery(self):
        for d in (self.request, self.receipt):
            d.update(card_ids=[], no_cards=True)
        self.write_report(body="\n# No cards due\n")
        self.assertEqual(self.check()["status"], "LANDED")

    def test_undeclared_empty_workload_fails(self):
        self.request.update(card_ids=[], no_cards=False)
        with self.assertRaisesRegex(landing.LandingFailure, "EMPTY_WORKLOAD"):
            self.check()

    def test_external_report_path_fails(self):
        self.receipt["report_path"] = "../GRADE_AND_REVIEW.md"
        with self.assertRaisesRegex(landing.LandingFailure, "PATH_INVALID"):
            self.check()

    def test_cli_failure_is_nonzero(self):
        self.assertEqual(landing.main([str(self.root / "absent.json"),
                                       str(self.root / "receipt.json")]), 1)


if __name__ == "__main__":
    unittest.main()
