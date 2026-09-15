import json
from pathlib import Path

from scripts.build_mlb_v8_replay_receipt import build


def test_mlb_replay_receipt_binds_policy_inputs_and_outputs(tmp_path: Path):
    policy = tmp_path / "policy.json"
    inputs = tmp_path / "inputs"
    archive = tmp_path / "archive"
    inputs.mkdir()
    archive.mkdir()

    policy.write_text('{"policy":"frozen"}\n', encoding="utf-8")
    (inputs / "snapshot.json").write_text('{"odds":1}\n', encoding="utf-8")
    (archive / "manifest.json").write_text('{"manifest":1}\n', encoding="utf-8")
    (archive / "gap_report.json").write_text('[]\n', encoding="utf-8")

    first = build(inputs, archive, policy)
    second = build(inputs, archive, policy)
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["metadata"]["forward_holdout_replacement_allowed"] is False
    assert first["promotion_authority"] is False

    names = {row["path"] for row in first["files"]}
    assert "policy/mlb_v8_evidence_policy.json" in names
    assert "inputs/snapshot.json" in names
    assert "outputs/manifest.json" in names
    assert "outputs/gap_report.json" in names

    stored = json.loads((archive / "receipt.json").read_text(encoding="utf-8"))
    assert stored["receipt_sha256"] == first["receipt_sha256"]

    (inputs / "snapshot.json").write_text('{"odds":2}\n', encoding="utf-8")
    changed = build(inputs, archive, policy)
    assert changed["receipt_sha256"] != first["receipt_sha256"]
