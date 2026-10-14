"""t118: shared registry gate on legacy runners + fail-closed UNREGISTERED.

Adversarial: every runner's emitted card is gated by the single helper in
sportsedge.registry_gate; blocked or unregistered markets that come back
PRICED are replaced by a blocker row carrying no probability/price/EV.
Offline, synthetic rows only (no real quotes, no fetches).
"""
import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from artifacts import run_it_full as R
from sportsedge import registry_gate as G

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]

BLOCKED_CASES = [("MLB", "STOLEN_BASES"), ("MLB", "BATTER_STOLEN_BASES"),
                 ("MLB", "PITCHER_HITS_WALKS_ER"), ("MLB", "F5_MONEYLINE"),
                 ("MLB", "F5_TOTALS"), ("NFL", "PLAYER_PASSING_YARDS"),
                 ("NFL", "ANYTIME_TD"), ("NFL", "receptions"),
                 ("NFL", "TEAM_TOTAL")]
UNREGISTERED_CASES = [("CFB", "PLAYER_PASSING_YARDS"), ("CFB", "ANYTIME_TD"),
                      ("CFB", "TEAM_TOTAL"), ("NBA", "PLAYER_POINTS"),
                      ("CBB", "FIRST_HALF_SPREAD"), ("MLB", "MADE_UP_MARKET"),
                      ("NFL", "ML_3WAY"), ("", "TOTAL")]


def _priced(sport, market):
    return {"sport": sport, "market": market, "side": "OVER", "line": 1.5,
            "price": -110, "model_p": 0.71, "probability": 0.71,
            "fair_odds": -245, "ev": 0.3, "edge": 0.18,
            "bet_status": "LEAN"}


def _no_price(row):
    assert not G.is_priced(row), row
    assert row["research_only"] is True and row["registry_enforced"] is True


@pytest.mark.parametrize("sport,market", BLOCKED_CASES)
def test_blocked_markets_blocked_by_shared_helper(sport, market):
    row = G.registry_blocked_row(sport, [market], {"market": market})
    assert row and row["blocker"] != G.UNREGISTERED


@pytest.mark.parametrize("sport,market", UNREGISTERED_CASES)
def test_unregistered_markets_fail_closed_unknown(sport, market):
    row = G.registry_blocked_row(sport, [market], {"market": market})
    assert row["blocker"] == "UNREGISTERED"
    assert row["registry_state"] == "UNKNOWN"


@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
@pytest.mark.parametrize("market", ["ML", "SPREAD", "TOTAL", "moneyline"])
def test_unregistered_sport_core_game_passes_but_is_labelled(sport, market):
    assert G.registry_blocked_row(sport, [market], {"market": market}) is None
    out, st = G.gate_payload({"results": [_priced(sport, market)]})
    assert out["results"][0]["registry_status"] == "SPORT_NOT_IN_REGISTRY"
    assert st["blocked"] == st["unregistered"] == 0


def test_registered_priced_markets_untouched():
    for sport, m in [("MLB", "PITCHER_STRIKEOUTS"), ("MLB", "ML"),
                     ("NFL", "SPREAD"), ("NFL", "total")]:
        assert G.registry_blocked_row(sport, [m], {"market": m}) is None
        out, _ = G.gate_payload([_priced(sport, m)])
        assert out[0]["model_p"] == 0.71 and "registry_status" not in out[0]


def test_gate_payload_nested_and_sport_inheritance():
    card = {"sport": "MLB", "cards": [{"rows": [
        {"market": "STOLEN_BASES", "model_p": 0.6, "ev": 0.1},
        {"market": "PITCHER_STRIKEOUTS", "model_p": 0.6}]}],
        "NFL": {"sport": "NFL", "props": [_priced("NFL", "PLAYER_RECEPTIONS")]},
        "CFB": {"sport": "CFB", "props": [_priced("CFB", "PLAYER_RUSHING_YARDS")]}}
    out, st = G.gate_payload(card)
    _no_price(out["cards"][0]["rows"][0])
    assert out["cards"][0]["rows"][1]["model_p"] == 0.6
    _no_price(out["NFL"]["props"][0])
    _no_price(out["CFB"]["props"][0])
    assert out["CFB"]["props"][0]["blocker"] == "UNREGISTERED"
    assert st == {"checked": 4, "blocked": 2, "unregistered": 1}


def test_unpriced_rows_keep_specific_reason():
    row = {"market": "STOLEN_BASES", "model_p": None,
           "reason": "ILLINOIS_COLLEGE_EXCLUDED"}
    out, st = G.gate_payload([row])
    assert out[0] == row and st["checked"] == 0


# ---- run_it_full: unregistered (CFB player prop) that a lane PRICES -----

def test_run_full_cfb_player_prop_priced_by_lane_is_blocked(monkeypatch):
    def leaky(rows, *a, **k):
        return [{"status": "RESEARCH_CANDIDATE_NOT_VALIDATED", "sport": "CFB",
                 "market": r["market"], "model_p": 0.8, "ev_per_dollar": 0.4,
                 "probability": 0.8} for r in rows], []
    monkeypatch.setattr(R, "phone_cfb_player_rows", leaky)
    line = {"sport": "CFB", "market": "PLAYER_PASSING_YARDS", "away": "AAA",
            "home": "BBB", "side": "OVER", "line": 250.5, "price": -110,
            "player_name": "Test Player", "book": "DK",
            "captured_at": NOW.isoformat()}
    card = R.run_full({"lines": [line]}, now=NOW, auto_context=False)
    row = card["evaluated_rows"][0]
    if row.get("status") == "RESEARCH_CANDIDATE_NOT_VALIDATED":
        pytest.fail("unregistered CFB prop kept a price")
    assert not G.is_priced(row)
    assert row["blocker"] == "UNREGISTERED" and row["registry_state"] == "UNKNOWN"
    assert card.get("prop_candidates", []) == []


# ---- per-runner wiring: gate is called, and before every card write ------

RUNNERS = {
    "scripts/run_auto_dk_cards.py": "main",
    "scripts/run_auto_mlb.py": "main",
    "scripts/run_auto_mlb_resilient.py": "main",
    "scripts/run_auto_nfl_resilient.py": "main",
    "scripts/run_nfl_lines_card.py": "main",
    "scripts/run_nfl_unified_lines_card.py": "main",
    "scripts/run_cfb_sdv_card_v2.py": "main",
    "scripts/run_manual_mlb_snapshot.py": "main",
}


@pytest.mark.parametrize("path,fn", sorted(RUNNERS.items()))
def test_runner_gates_before_every_card_write(path, fn):
    tree = ast.parse((ROOT / path).read_text())
    func = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == fn)
    gates, writes = [], []
    for n in ast.walk(func):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name == "_registry_gate_and_stamp":
                gates.append(n.lineno)
            if name == "write_text" and n.args and "dumps" in ast.unparse(n.args[0]) \
                    and "full_board" not in ast.unparse(n.args[0]):
                writes.append(n.lineno)
    assert gates, path
    for w in writes:
        assert any(g < w for g in gates), (path, w)
    src = (ROOT / path).read_text()
    assert "from sportsedge.registry_gate import gate_and_stamp" in src
    assert "def registry_blocked_row" not in src  # never duplicated


def test_run_auto_nfl_resilient_board_output_is_gated_payload():
    # full_board is read from the already-gated payload
    src = (ROOT / "scripts/run_auto_nfl_resilient.py").read_text()
    assert src.index('payload = _registry_gate_and_stamp(payload, "NFL"', 
                     src.index("board_path = ")-400) < src.index("board_path = ")


def test_live_run_it_card_gated(monkeypatch):
    from sportsedge import live_run_it as L
    def leak(i, line, *a, **k):
        return {"input_index": i, "sport": "NFL", "status": "LIVE_CANDIDATE",
                "market": "PLAYER_PASSING_YARDS", "model_p": 0.9, "ev": 0.5,
                "research_only": True}
    monkeypatch.setattr(L, "_price_live_line", leak)
    card = L.run_live_full({"lines": [{"sport": "NFL", "market": "ML",
                                       "side": "HOME", "home": "BBB",
                                       "away": "AAA", "price": -110}]}, now=NOW)
    for r in card["evaluated_rows"]:
        assert not G.is_priced(r)
    assert card["registry_gate"]["blocked"] >= 1


def test_unified_card_blocks_registry_blocked_generic_markets(monkeypatch):
    from sportsedge import unified_card as U
    monkeypatch.setattr(U, "validate_canonical_quote", lambda q: dict(q))
    called = []
    monkeypatch.setattr(U, "run_generic_card",
                        lambda **k: called.append(k) or [])
    quotes = [{"market": m, "game_id": "g1", "entity_id": "p1", "line": 0.5,
               "side": "OVER", "american_odds": -110}
              for m in ["STOLEN_BASES", "PITCHER_HITS_WALKS_ER", "F5_MONEYLINE",
                        "HITS_STOLEN_BASES", "TRIPLES"]]
    out = U.run_unified_card(games=[], feature_rows=[], quotes=quotes,
                             ingestion_now=NOW, finalization_now=NOW)
    assert called == []
    assert [r.bet_status for r in out] == ["BLOCKED"] * 5
    assert all(r.model_p is None and r.reason.startswith("REGISTRY_") for r in out)
