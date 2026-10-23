"""gap_ledger() verifies remote SHAs by default; offline is explicit and marked."""
import json
import os
import sys
from pathlib import Path

import pytest

from scripts import completion_gap_ledger as L

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_network_main_check(monkeypatch, request):
    if "real_verified" not in request.node.name and "asks_main" not in request.node.name:
        monkeypatch.setattr(L, "_main_has_file", lambda path: False)


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


# ---- t251: cited SHAs are the cleared branch HEADs; merged-to-main detection ----
import hashlib  # noqa: E402

POLICY = json.loads((ROOT / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))
SIT = ("grok/t247-situational-price-guard-20261023", "ea53ee161a7b8f32cced1c44f7322e795e4ddcbf")
DEF = ("grok/t244-team-defense-cluster-20261023", "9c2b0af35601711d1c2c79327e341f9435310ff5")
PER = ("grok/t249-period-quarter-spreads-refused-20261023", "2399e92bbcf4793620d6d79b4b09184377c0f6bd")
SIT_MARKETS = ("both_teams_to_score_n", "defensive_special_teams_td", "first_score",
               "largest_lead", "safety")
PERIOD_MARKETS = ("first_half_moneyline", "first_half_spread", "first_half_total",
                  "second_half_moneyline", "second_half_spread", "second_half_total",
                  "quarter_moneyline", "quarter_spread", "quarter_total")


def _entries():
    for key in ("grok_branch_engines", "grok_branch_screen_engines"):
        for sport, ms in POLICY[key].items():
            for m, e in ms.items():
                yield key, sport, m, e


def test_policy_points_at_current_heads():
    g = POLICY["grok_branch_engines"]["NFL"]
    for m in SIT_MARKETS:
        assert (g[m]["branch"], g[m]["sha"]) == SIT, m
        assert g[m]["engine_file"] == "sportsedge/nfl_situational_empirical.py"
    for m in ("team_sacks", "team_turnovers"):
        assert (g[m]["branch"], g[m]["sha"]) == DEF, m
        assert g[m]["engine_file"] == "sportsedge/nfl_team_defense_counts_empirical.py"
    s = POLICY["grok_branch_screen_engines"]["NFL"]
    assert set(s) == set(PERIOD_MARKETS)
    for m in PERIOD_MARKETS:
        assert (s[m]["branch"], s[m]["sha"]) == PER, m
        assert s[m]["engine_file"] == "sportsedge/nfl_period_lines_empirical.py"


def test_every_entry_cites_cleared_head_equal_to_sha_and_engine_file():
    for key, sport, m, e in _entries():
        assert e["cleared_head_sha"] == e["sha"], (key, m)
        assert e["engine_file"].startswith("sportsedge/") and e["engine_file"].endswith(".py")


def test_sha_differing_from_cleared_head_refuses():
    bad = json.loads(json.dumps(POLICY))
    bad["grok_branch_engines"]["NFL"]["safety"]["cleared_head_sha"] = "a" * 40
    with pytest.raises(L.LedgerRefusal, match="GROK_BRANCH_SHA_NOT_CLEARED_HEAD:safety"):
        L.verify_branch_shas(bad, resolver=lambda b, s: "head")


def test_missing_cleared_head_refuses():
    bad = json.loads(json.dumps(POLICY))
    del bad["grok_branch_screen_engines"]["NFL"]["quarter_total"]["cleared_head_sha"]
    with pytest.raises(L.LedgerRefusal, match="GROK_BRANCH_SHA_NOT_CLEARED_HEAD:quarter_total"):
        L.verify_branch_shas(bad, resolver=lambda b, s: "head")


def test_ancestor_of_head_is_not_enough():
    with pytest.raises(L.LedgerRefusal, match="GROK_BRANCH_SHA_NOT_HEAD"):
        L.verify_branch_shas(POLICY, resolver=lambda b, s: "ancestor")


def test_screen_engine_pairs_are_verified_too():
    seen = []
    L.verify_branch_shas(POLICY, resolver=lambda b, s: seen.append((b, s)) or "head")
    assert PER in seen and SIT in seen and DEF in seen


@pytest.mark.parametrize("status,want", [("identical", "head"), ("ahead", "ancestor"),
                                         ("behind", "missing"), ("diverged", "missing")])
def test_real_resolver_requires_identical(monkeypatch, status, want):
    import io
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: io.BytesIO(json.dumps({"status": status}).encode()))
    assert L._github_resolver("grok/x", "a" * 40) == want


def _row(market):
    return {"sport": "NFL", "market": market, "blocker": "NO_ENGINE",
            "readiness": "NO_CANONICAL_PRICING_PATH", "validated_accuracy_in_this_audit": False}


def test_engine_merged_into_main_gets_its_own_status():
    merged = frozenset({"sportsedge/nfl_situational_empirical.py"})
    g = L.classify(_row("safety"), POLICY, merged_files=merged)
    assert g["status"] == "ENGINE_MERGED_TO_MAIN_NOT_WIRED"
    assert g["engine_ref"]["engine_file"] == "sportsedge/nfl_situational_empirical.py"
    assert L.classify(_row("safety"), POLICY)["status"] == "ENGINE_ON_GROK_BRANCH_NOT_MERGED"


def test_online_ledger_asks_main_for_every_engine_file(monkeypatch):
    asked = []
    monkeypatch.setattr(L, "verify_branch_shas", lambda policy, **kw: [])
    monkeypatch.setattr(L, "_main_has_file",
                        lambda path: asked.append(path) or path.endswith("team_defense_counts_empirical.py"))
    led = L.gap_ledger()
    files = {e["engine_file"] for _, _, _, e in _entries()}
    assert files <= set(asked)
    st = {g["market"]: g for g in led["gaps"] if g["sport"] == "NFL"}
    assert st["team_sacks"]["status"] == "ENGINE_MERGED_TO_MAIN_NOT_WIRED"
    assert st["safety"]["status"] == "ENGINE_ON_GROK_BRANCH_NOT_MERGED"


def test_offline_ledger_never_asks_main(monkeypatch):
    monkeypatch.setattr(L, "_main_has_file", lambda path: pytest.fail("asked main offline"))
    assert L.gap_ledger(offline=True)["remote_shas_verified"] is False


def test_period_rows_cite_screen_engine():
    led = json.loads((ROOT / "research" / "completion_gap_ledger_20261023.json").read_text())
    st = {g["market"]: g for g in led["gaps"] if g["sport"] == "NFL"}
    for m in PERIOD_MARKETS:
        se = st[m]["screen_engine"]
        assert (se["branch"], se["sha"]) == PER and se["merged_to_main"] is False
    assert "MONEYLINE_DERIVABLE" in st["quarter_spread"]["screen_engine"]["refusals"]


def test_rulings_doc_is_t249_copy_base():
    text = (ROOT / "docs" / "decisions" / "GROK_RULINGS_20261023.md").read_bytes()
    assert hashlib.sha256(text).hexdigest() == (
        "afa310851a189b565b35dc3df1f6748102bb2f6bf83a66d65edb343fb25bc513")
