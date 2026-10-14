"""Malformed local inputs must produce exclusions, never crash the runner."""
import json

import pytest

from sportsedge.prepricing.qb_form2_bundle_loader import load_form2_bundles


@pytest.mark.parametrize("team", [["bad"], "bad", 42, True])
def test_malformed_team_is_audited_without_crashing(tmp_path, team):
    (tmp_path / "bundle.json").write_text(json.dumps({"team": team}))
    mapping, audit = load_form2_bundles(tmp_path, [])
    assert mapping == {}
    assert audit["admitted_team_ids"] == []
    assert audit["entries"][0]["disposition"] == "EXCLUDED"
    assert audit["entries"][0]["team_id"] is None


def test_invalid_utf8_is_audited_without_crashing(tmp_path):
    (tmp_path / "bundle.json").write_bytes(b"\xff")
    mapping, audit = load_form2_bundles(tmp_path, [])
    assert mapping == {}
    assert audit["admitted_team_ids"] == []
    assert audit["entries"][0]["reason"] == "BUNDLE_FILE_UNREADABLE"
    assert audit["entries"][0]["detail"] == "UnicodeDecodeError"
