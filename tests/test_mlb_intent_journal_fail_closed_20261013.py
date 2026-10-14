"""Adversarial journal schema/state tests for the offline MLB recovery path.

No network calls, source capture, holdout data, or model authority.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.sports.mlb import starter_capture as sc


SCHEMA = sc.SCHEMA_INTENT
IDENT = "a" * 64
DIGEST = "b" * 64


def _begin(**overrides):
    value = {
        "schema": SCHEMA,
        "intent_id": IDENT,
        "state": "BEGIN",
        "base_seq": 0,
        "record_sha256": DIGEST,
        "record_line": '{}\n',
        "raw_sha256": None,
        "receipt_link": {"sha256": None, "url": None},
    }
    value.update(overrides)
    return value


class IntentJournalFailClosedTests(unittest.TestCase):
    def _paths(self, temp):
        root = Path(temp)
        capture, manifest, raw = root / "capture.jsonl", root / "manifest.jsonl", root / "raw"
        return capture, manifest, raw, root / "manifest.jsonl.intent.jsonl"

    def _verify_and_recover_reject(self, entries, expected):
        with tempfile.TemporaryDirectory() as root:
            capture, manifest, raw, journal = self._paths(root)
            journal.write_bytes(b"".join(
                (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode()
                if isinstance(obj, dict) else obj for obj in entries
            ))
            result = sc.verify_capture_store(capture, manifest, raw)
            self.assertFalse(result["ok"], result)
            self.assertIn(expected, result["failure"]["reason"])
            original = journal.read_bytes()
            with self.assertRaises(sc.StarterCaptureError) as caught:
                sc.recover_capture_store(capture, manifest, raw)
            self.assertIn(expected, str(caught.exception))
            self.assertEqual(journal.read_bytes(), original)

    def test_missing_id_and_recovery_fields_rejected(self):
        examples = [
            {k: v for k, v in _begin().items() if k != "intent_id"},
            {k: v for k, v in _begin().items() if k != "record_line"},
            _begin(base_seq=True),
            _begin(base_seq=-1),
            _begin(raw_sha256="not-a-digest"),
            _begin(receipt_link=[]),
            _begin(receipt_link={"sha256": "bad", "url": None}),
            _begin(state="FUTURE_STATE"),
            {"schema": SCHEMA, "state": "COMMIT"},
        ]
        for value in examples:
            with self.subTest(value=value):
                self._verify_and_recover_reject([value], "INTENT_LINE_INVALID")

    def test_orphan_terminal_rejected(self):
        for state in ("COMMIT", "ABORT"):
            with self.subTest(state=state):
                self._verify_and_recover_reject(
                    [{"schema": SCHEMA, "intent_id": IDENT, "state": state}],
                    "INTENT_ORPHAN_TERMINAL",
                )

    def test_duplicate_begin_and_duplicate_commit_rejected(self):
        begin = _begin()
        commit = {"schema": SCHEMA, "intent_id": IDENT, "state": "COMMIT"}
        self._verify_and_recover_reject([begin, begin], "INTENT_DUPLICATE_BEGIN")
        self._verify_and_recover_reject([begin, commit, commit], "INTENT_ORPHAN_TERMINAL")

    def test_duplicate_json_key_rejected(self):
        bad = ('{"schema":"' + SCHEMA + '","schema":"' + SCHEMA
               + '","intent_id":"' + IDENT + '","state":"COMMIT"}\n').encode()
        self._verify_and_recover_reject([bad], "INTENT_DUPLICATE_JSON_KEY")

    def test_nonfinite_json_rejected(self):
        bad = ('{"schema":"' + SCHEMA + '","intent_id":"' + IDENT
               + '","state":"BEGIN","extra":NaN}\n').encode()
        self._verify_and_recover_reject([bad], "INTENT_NONFINITE_NUMBER")

    def test_bad_record_json_fails_as_controlled_recovery_error(self):
        record_line = 'not-json\n'
        raw = record_line.encode()
        begin = _begin(record_line=record_line, record_sha256=hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as root:
            capture, manifest, raw_dir, journal = self._paths(root)
            journal.write_text(json.dumps(begin) + "\n")
            result = sc.verify_capture_store(capture, manifest, raw_dir)
            self.assertFalse(result["ok"])
            self.assertEqual(result["failure"]["reason"], "INTENT_UNCOMMITTED")
            with self.assertRaisesRegex(sc.StarterCaptureError, "INTENT_RECORD_UNPARSEABLE"):
                sc.recover_capture_store(capture, manifest, raw_dir)

    def test_retry_after_explicit_abort_is_permitted_by_state_machine(self):
        begin = _begin()
        abort = {"schema": SCHEMA, "intent_id": IDENT, "state": "ABORT", "reason": "RAW_MISSING"}
        self.assertEqual(sc._pending([begin, abort, begin]), [begin])


if __name__ == "__main__":
    unittest.main()
