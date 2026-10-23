"""gap_ledger() verifies remote SHAs by default; offline is explicit and marked."""
import json
import os
import sys
from pathlib import Path

import pytest

from scripts import completion_gap_ledger as L

ROOT = Path(__file__).resolve().parents[1]


def test_library_default_verifies(monkeypatch):
    calls = []
    monkeypatch.setattr(L, "verify_branch_shas", lambda policy, **kw: calls.append(1) or [])
    led = L.gap_ledger()
    assert calls == [1] and led["remote_shas_verified"] is True


def test_library_offline_is_explicit_and_marked(monkeypatch):
    monkeypatch.setattr(L, "verify_branch_shas", lambda *a, **k: pytest.fail("verified offline"))
    assert L.gap_ledger(offline=True)["remote_shas_verified"] is False


def test_library_remote_failure_raises_not_unverified_output(monkeypatch):
    def boom(policy, **kw):
        raise L.LedgerRefusal("REMOTE_CHECK_UNAVAILABLE")
    monkeypatch.setattr(L, "verify_branch_shas", boom)
    with pytest.raises(L.LedgerRefusal):
        L.gap_ledger()


@pytest.mark.parametrize("bad", [None, 0, 1, "yes"])
def test_offline_flag_must_be_bool(bad):
    with pytest.raises(L.LedgerRefusal, match="OFFLINE_FLAG_MUST_BE_BOOL"):
        L.gap_ledger(offline=bad)


def test_cli_offline_output_carries_false_field(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "verify_branch_shas", lambda *a, **k: pytest.fail("verified offline"))
    out = tmp_path / "o.json"
    monkeypatch.setattr(sys, "argv", ["ledger", "--offline", "--out", str(out)])
    assert L.main() == 0
    assert json.loads(out.read_text())["remote_shas_verified"] is False


def test_cli_default_output_carries_true_field(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "verify_branch_shas", lambda policy, **kw: [])
    out = tmp_path / "o.json"
    monkeypatch.setattr(sys, "argv", ["ledger", "--out", str(out)])
    assert L.main() == 0
    assert json.loads(out.read_text())["remote_shas_verified"] is True


def test_committed_ledger_is_the_verified_one():
    led = json.loads((ROOT / "research" / "completion_gap_ledger_20261023.json").read_text())
    assert led["remote_shas_verified"] is True


@pytest.mark.skipif(os.environ.get("SPORTSEDGE_LEDGER_REMOTE_CHECK") != "1",
                    reason="network check; set SPORTSEDGE_LEDGER_REMOTE_CHECK=1")
def test_committed_bytes_match_real_verified_regeneration():
    path = ROOT / "research" / "completion_gap_ledger_20261023.json"
    assert path.read_bytes() == L.render(L.gap_ledger()).encode("utf-8")
