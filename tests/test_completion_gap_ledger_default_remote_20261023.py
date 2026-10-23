"""--verify-remote is the default; offline needs an explicit opt-out."""
import sys

import pytest

from scripts import completion_gap_ledger as L


def _no_github(monkeypatch):
    """Unit tests never reach GitHub: every remote primitive is mocked."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network in unit test"))
    monkeypatch.setattr(L, "_main_merge_state", lambda path, head: "NOT_ON_MAIN")


def _run(monkeypatch, argv, tmp_path):
    calls = []
    _no_github(monkeypatch)
    monkeypatch.setattr(L, "verify_branch_shas", lambda policy, **kw: calls.append(1) or [])
    monkeypatch.setattr(sys, "argv", ["ledger", "--out", str(tmp_path / "o.json"), *argv])
    assert L.main() == 0
    return calls


def test_remote_verification_runs_by_default(monkeypatch, tmp_path):
    assert _run(monkeypatch, [], tmp_path) == [1]


def test_explicit_offline_opt_out_skips_remote(monkeypatch, tmp_path):
    assert _run(monkeypatch, ["--offline"], tmp_path) == []


def test_offline_output_is_marked_unverified(monkeypatch, tmp_path, capsys):
    _run(monkeypatch, ["--offline"], tmp_path)
    assert "REMOTE_SHAS_NOT_VERIFIED_OFFLINE" in capsys.readouterr().err


def test_remote_failure_blocks_output(monkeypatch, tmp_path):
    def boom(policy, **kw):
        raise L.LedgerRefusal("REMOTE_CHECK_UNAVAILABLE")
    monkeypatch.setattr(L, "verify_branch_shas", boom)
    monkeypatch.setattr(sys, "argv", ["ledger", "--out", str(tmp_path / "o.json")])
    with pytest.raises(L.LedgerRefusal):
        L.main()
    assert not (tmp_path / "o.json").exists()


@pytest.mark.skipif(__import__("os").environ.get("SPORTSEDGE_LEDGER_REMOTE_CHECK") != "1",
                    reason="live GitHub check; set SPORTSEDGE_LEDGER_REMOTE_CHECK=1")
def test_remote_verification_runs_live_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ledger", "--out", str(tmp_path / "o.json")])
    assert L.main() == 0
