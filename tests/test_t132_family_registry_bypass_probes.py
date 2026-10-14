"""Grok t132 independent-verification probes for #2217 (exact head 45697a31).

Each probe asserts the *intended* fail-closed behaviour and is marked
xfail(strict=True) because it does NOT hold at the reviewed head. When the
hole is closed the test XPASSes, strict mode fails, and the marker must be
removed -- so these cannot silently rot. Probes only read code; no network,
no data, no activation.
"""
import pathlib
import pytest

from sportsedge.canonical_coverage import resolve_market

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAMILY_MARKETS = [(s, m) for s in ("CFB", "NBA", "CBB")
                  for m in ("ML", "SPREAD", "TOTAL", "PLAYER_POINTS")]


@pytest.mark.xfail(strict=True, reason="t132: CFB/NBA/CBB have no canonical "
                   "registry entry; run_full's _registry_blocked_row only "
                   "blocks resolve_market()==BLOCKED, so None passes through")
@pytest.mark.parametrize("sport,market", FAMILY_MARKETS)
def test_family_markets_resolve_in_canonical_registry(sport, market):
    assert resolve_market(sport, market) is not None


@pytest.mark.xfail(strict=True, reason="t132: family_market_decision has no "
                   "production caller (only its own unit test)")
def test_family_market_decision_has_production_caller():
    callers = [p for d in ("sportsedge", "scripts", "artifacts")
               for p in (ROOT / d).rglob("*.py")
               if p.name != "family_market_registry.py"
               and "family_market_decision" in p.read_text(errors="ignore")]
    assert callers


LEGACY = ["run_cfb_paper_market", "run_cfb_prop_model_candidate",
          "run_cfb_game_model_candidate", "run_nba_lines_issue",
          "run_auto_cfb_resilient", "run_cfb_auto"]
GATE_TOKENS = ("family_market_decision", "canonical_coverage", "run_full",
               "_registry_blocked_row", "registry_gate")


@pytest.mark.xfail(strict=True, reason="t132: workflow-invoked legacy "
                   "CFB/NBA runners reference no registry gate")
@pytest.mark.parametrize("script", LEGACY)
def test_workflow_invoked_family_runner_is_registry_gated(script):
    src = (ROOT / "scripts" / f"{script}.py").read_text()
    assert any(t in src for t in GATE_TOKENS)
