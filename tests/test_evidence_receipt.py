from __future__ import annotations

import json
from pathlib import Path

from sportsedge.core.validation.evidence_receipt import (
    build_receipt,
    canonical_json_bytes,
    verify_receipt,
    write_receipt,
)


def test_receipt_is_deterministic_and_binds_policy_inputs_outputs(tmp_path: Path) -> None:
    policy = tmp_path / "policy.json"
    source = tmp_path / "raw" / "source.json"
    output = tmp_path / "artifacts" / "manifest.json"
    source.parent.mkdir()
    output.parent.mkdir()
    policy.write_text('{"frozen":true}\n', encoding="utf-8")
    source.write_text('{"price":-110}\n', encoding="utf-8")
    output.write_text('{"rows":1}\n', encoding="utf-8")

    kwargs = {
        "lane": "MLB_REPLAY",
        "root": tmp_path,
        "inputs": [source],
        "outputs": [output],
        "policy_path": policy,
        "metadata": {"selection": "EARLY_ONLY_AT_OR_BEFORE_TARGET"},
    }
    first = build_receipt(**kwargs)
    second = build_receipt(**kwargs)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert verify_receipt(first, root=tmp_path) == []
    assert first["authority"]["official_authority"] is False
    assert first["authority"]["promotion_authority"] is False


def test_receipt_detects_mutated_evidence(tmp_path: Path) -> None:
    source = tmp_path / "capture.json"
    source.write_text('{"line":3}\n', encoding="utf-8")
    receipt = build_receipt(lane="NFL_FORWARD_CAPTURE", root=tmp_path, inputs=[source])
    source.write_text('{"line":3.5}\n', encoding="utf-8")

    errors = verify_receipt(receipt, root=tmp_path)
    assert "INPUTS_0:SHA256_MISMATCH" in errors
    assert "INPUTS_0:BYTE_COUNT_MISMATCH" in errors


def test_written_receipt_round_trips(tmp_path: Path) -> None:
    source = tmp_path / "cfb.ndjson"
    source.write_text('{"captured_at":"2026-09-12T20:00:00Z"}\n', encoding="utf-8")
    receipt = build_receipt(lane="CFB_FORWARD_CAPTURE", root=tmp_path, inputs=[source])
    destination = tmp_path / "receipt.json"
    write_receipt(destination, receipt)

    loaded = json.loads(destination.read_text(encoding="utf-8"))
    assert loaded == receipt
    assert verify_receipt(loaded, root=tmp_path) == []
