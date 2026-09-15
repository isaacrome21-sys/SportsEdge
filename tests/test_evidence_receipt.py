from pathlib import Path

import pytest

from sportsedge.core.validation.evidence_receipt import (
    EvidenceReceiptError,
    build_evidence_receipt,
    verify_evidence_receipt,
)


def test_receipt_is_order_independent_and_mutation_sensitive(tmp_path: Path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text('{"a":1}\n', encoding="utf-8")
    b.write_text('{"b":2}\n', encoding="utf-8")

    r1 = build_evidence_receipt(
        [("inputs/a.json", a), ("inputs/b.json", b)],
        sport="mlb",
        purpose="replay",
        metadata={"target_direction": "EARLY_ONLY_AT_OR_BEFORE_TARGET"},
    )
    r2 = build_evidence_receipt(
        [("inputs/b.json", b), ("inputs/a.json", a)],
        sport="mlb",
        purpose="replay",
        metadata={"target_direction": "EARLY_ONLY_AT_OR_BEFORE_TARGET"},
    )
    assert r1["receipt_sha256"] == r2["receipt_sha256"]
    assert r1["promotion_authority"] is False

    assert verify_evidence_receipt(
        r1, {"inputs/a.json": a, "inputs/b.json": b}
    )["status"] == "PASS"

    a.write_text('{"a":9}\n', encoding="utf-8")
    checked = verify_evidence_receipt(
        r1, {"inputs/a.json": a, "inputs/b.json": b}
    )
    assert checked["status"] == "FAIL"
    assert "SHA256_MISMATCH:inputs/a.json" in checked["differences"]


def test_receipt_rejects_unsafe_or_duplicate_logical_paths(tmp_path: Path):
    file_path = tmp_path / "x"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(EvidenceReceiptError):
        build_evidence_receipt(
            [("../escape", file_path)], sport="cfb", purpose="audit"
        )
    with pytest.raises(EvidenceReceiptError):
        build_evidence_receipt(
            [("x", file_path), ("x", file_path)], sport="cfb", purpose="audit"
        )
