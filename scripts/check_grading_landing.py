"""Verify a grading run landed; never grade or infer results from file existence.

Usage: python scripts/check_grading_landing.py REQUEST.json RECEIPT.json
The scheduler freezes REQUEST before launch; the grader writes RECEIPT last.
Both use schema_version=1, run_id, input_sha256, and card_ids. Receipt also
names report_path (relative to receipt) and report_sha256. Empty workloads
must be explicit (no_cards=true in both documents). A report is still required.
This verifies delivery integrity, not the correctness of grades.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


class LandingFailure(ValueError):
    pass


def _read(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LandingFailure("GRADING_LANDING_MISSING_OR_INVALID_JSON") from exc
    if not isinstance(doc, dict):
        raise LandingFailure("GRADING_LANDING_INVALID_DOCUMENT")
    return doc


def _identity(doc):
    if type(doc.get("schema_version")) is not int or doc["schema_version"] != 1:
        raise LandingFailure("GRADING_LANDING_SCHEMA_INVALID")
    if not isinstance(doc.get("run_id"), str) or not doc["run_id"].strip():
        raise LandingFailure("GRADING_LANDING_RUN_ID_MISSING")
    if not isinstance(doc.get("input_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", doc["input_sha256"]):
        raise LandingFailure("GRADING_LANDING_INPUT_HASH_INVALID")
    ids = doc.get("card_ids")
    if not isinstance(ids, list) or any(
            not isinstance(x, str) or not x.strip() for x in ids):
        raise LandingFailure("GRADING_LANDING_CARD_IDS_INVALID")
    if len(set(ids)) != len(ids):
        raise LandingFailure("GRADING_LANDING_DUPLICATE_CARD")
    if type(doc.get("no_cards")) is not bool or doc["no_cards"] != (len(ids) == 0):
        raise LandingFailure("GRADING_LANDING_EMPTY_WORKLOAD_NOT_DECLARED")
    return doc["run_id"], doc["input_sha256"], frozenset(ids), doc["no_cards"]


def check_landing(request_path, receipt_path):
    request, receipt = _read(request_path), _read(receipt_path)
    if _identity(request) != _identity(receipt):
        raise LandingFailure("GRADING_LANDING_REQUEST_MISMATCH")
    relative = receipt.get("report_path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise LandingFailure("GRADING_LANDING_REPORT_PATH_INVALID")
    base = Path(receipt_path).resolve().parent
    report = (base / relative).resolve()
    if not report.is_relative_to(base) or report.name != "GRADE_AND_REVIEW.md":
        raise LandingFailure("GRADING_LANDING_REPORT_PATH_INVALID")
    try:
        data = report.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise LandingFailure("GRADING_LANDING_REPORT_MISSING_OR_UNREADABLE") from exc
    if not text.strip():
        raise LandingFailure("GRADING_LANDING_REPORT_EMPTY")
    digest = hashlib.sha256(data).hexdigest()
    if digest != receipt.get("report_sha256"):
        raise LandingFailure("GRADING_LANDING_REPORT_HASH_MISMATCH")
    # The report itself must name this run, not merely a new sidecar pointing
    # at yesterday's file. Grader emits this machine-readable first line.
    binding = {"run_id": request["run_id"], "input_sha256": request["input_sha256"],
               "card_ids": sorted(request["card_ids"]), "no_cards": request["no_cards"]}
    expected = "<!-- grading-run " + json.dumps(binding, sort_keys=True) + " -->"
    if text.splitlines()[0] != expected:
        raise LandingFailure("GRADING_LANDING_REPORT_BINDING_MISMATCH")
    return {"status": "LANDED", **binding, "report_sha256": digest,
            "grades_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    parser.add_argument("receipt")
    args = parser.parse_args(argv)
    try:
        result = check_landing(args.request, args.receipt)
    except LandingFailure as exc:
        print(json.dumps({"status": "GRADING_LANDING_FAILED", "reason": str(exc)}),
              file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
