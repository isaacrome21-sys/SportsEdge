"""t126: registry gate on the 5 remaining legacy runners, and the gate
moved BEFORE image/text rendering (run_auto_dk_cards.image_card,
render_nfl_myspari_card). Offline, synthetic rows only."""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from sportsedge import registry_gate as G

ROOT = Path(__file__).resolve().parents[1]


def _load(rel):
    spec = importlib.util.spec_from_file_location(
        "t126_" + Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _calls(func, names):
    out = []
    for n in ast.walk(func):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name in names:
                out.append((n.lineno, name))
    return sorted(out)


def _func(rel, fn):
    tree = ast.parse((ROOT / rel).read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == fn)


# runner -> (gate function name, number of card writes it must precede)
RUNNERS = {
    "scripts/run_auto_cfb_resilient.py": ("_registry_gate_and_stamp", {"write_text"}, 3),
    "scripts/run_nfl_coherent_props.py": ("_registry_gate_and_stamp", {"write_text"}, 1),
    "scripts/run_cfb_sdv_card.py": ("_registry_gate_and_stamp", {"write_text"}, 1),
    "scripts/run_nfl_fair_odds_card.py": ("_registry_gate_odds_events", {"render_card"}, 1),
}


@pytest.mark.parametrize("path", sorted(RUNNERS))
def test_runner_gates_before_every_card_write(path):
    gate, writes, n = RUNNERS[path]
    seq = _calls(_func(path, "main"), {gate} | writes)
    write_lines = [ln for ln, name in seq if name in writes]
    gate_lines = [ln for ln, name in seq if name == gate]
    assert gate_lines, path
    if path.endswith("run_nfl_fair_odds_card.py"):
        # quota-skip / fetch-failure notices carry no prices; the priced
        # markdown is rendered only after the gate.
        assert min(gate_lines) < min(write_lines)
        return
    assert len(write_lines) == n == len(gate_lines)
    for w in write_lines:
        assert any(g < w for g in gate_lines), (path, w)


def test_image_card_gates_before_render():
    seq = _calls(_func("scripts/run_auto_dk_cards.py", "image_card"),
                 {"_registry_gate_card_file", "call"})
    assert [name for _, name in seq] == ["_registry_gate_card_file", "call"]


def test_render_nfl_myspari_gates_before_render():
    seq = _calls(_func("scripts/render_nfl_myspari_card.py", "main"),
                 {"_registry_gate_and_stamp", "render"})
    assert [name for _, name in seq] == ["_registry_gate_and_stamp", "render"]


def test_image_card_renders_only_gated_copy(tmp_path, monkeypatch):
    mod = _load("scripts/run_auto_dk_cards.py")
    card = tmp_path / "card.json"
    card.write_text(json.dumps({"sport": "NFL", "results": [
        {"market": "PLAYER_PASSING_YARDS", "model_p": 0.7, "ev": 0.2},
        {"market": "SPREAD", "model_p": 0.55}]}))
    seen = {}

    def fake_call(cmd, **k):
        seen["card"] = cmd[cmd.index("--card") + 1]
        return True, ""
    monkeypatch.setattr(mod, "call", fake_call)
    monkeypatch.setattr(mod, "ROOT", ROOT)
    assert mod.image_card(card, "NFL", tmp_path / "x.png") == "READY"
    gated = json.loads(Path(seen["card"]).read_text())
    assert Path(seen["card"]) != card
    assert not G.is_priced(gated["results"][0])
    assert gated["results"][1]["model_p"] == 0.55
    assert gated["registry_gate"]["blocked"] == 1


def test_image_card_unreadable_card_not_rendered(tmp_path, monkeypatch):
    mod = _load("scripts/run_auto_dk_cards.py")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setattr(mod, "call", lambda *a, **k: pytest.fail("rendered"))
    monkeypatch.setattr(mod, "ROOT", ROOT)
    assert mod.image_card(bad, "NFL", tmp_path / "x.png") == \
        "PNG_UNAVAILABLE:REGISTRY_GATE_UNREADABLE_CARD"


def test_render_nfl_myspari_text_drawn_from_gated_engine(tmp_path, monkeypatch):
    mod = _load("scripts/render_nfl_myspari_card.py")
    engine = tmp_path / "engine.json"
    engine.write_text(json.dumps({"games": [], "rows": [
        {"market": "ANYTIME_TD", "model_p": 0.4, "ev": 0.1},
        {"market": "SPREAD", "model_p": 0.52}]}))
    snap = tmp_path / "snap.json"
    snap.write_text("{}")
    seen = {}
    monkeypatch.setattr(mod, "render", lambda e, *a: seen.setdefault("e", e) and "")
    monkeypatch.setattr(mod, "attach_game_info", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_history", lambda *a, **k: {})
    monkeypatch.delenv("ISSUE", raising=False)
    monkeypatch.setattr(sys, "argv", ["x", "--engine-output", str(engine),
                                      "--snapshot", str(snap), "--out-dir",
                                      str(tmp_path / "out")])
    assert mod.main() == 0
    rows = seen["e"]["rows"]
    assert not G.is_priced(rows[0]) and rows[0]["registry_enforced"] is True
    assert rows[1]["model_p"] == 0.52
    assert seen["e"]["registry_gate"]["runner"] == "scripts/render_nfl_myspari_card.py"


def _event(*keys):
    return {"id": "e1", "commence_time": "2026-10-18T17:00:00Z",
            "home_team": "A", "away_team": "B",
            "bookmakers": [{"key": "draftkings", "markets": [
                {"key": k, "outcomes": []} for k in keys]}]}


def test_odds_api_events_gate():
    events, st = G.gate_odds_api_events(
        [_event("h2h", "spreads", "totals", "team_totals",
                "player_pass_yds", "")], "NFL", "t")
    kept = [m["key"] for m in events[0]["bookmakers"][0]["markets"]]
    assert kept == ["h2h", "spreads", "totals"]
    assert st["checked"] == 6 and st["blocked"] == 1 and st["unregistered"] == 2


def test_odds_api_events_gate_does_not_mutate_input():
    ev = _event("team_totals")
    G.gate_odds_api_events([ev], "NFL", "t")
    assert ev["bookmakers"][0]["markets"][0]["key"] == "team_totals"


@pytest.mark.parametrize("rel,sport", [
    ("scripts/run_auto_cfb_resilient.py", "CFB"),
    ("scripts/run_nfl_auto_gated.py", "NFL"),
    ("scripts/run_nfl_coherent_props.py", "NFL"),
    ("scripts/run_cfb_sdv_card.py", "CFB"),
])
def test_runner_gate_blocks_priced_blocked_market(rel, sport):
    mod = _load(rel)
    card = {"results": [{"market": "PLAYER_RUSHING_YARDS", "model_p": 0.8,
                         "edge": 0.3}, {"market": "SPREAD", "model_p": 0.51}]}
    out = mod._registry_gate_and_stamp(card, sport, rel)
    assert not G.is_priced(out["results"][0])
    assert out["results"][1]["model_p"] == 0.51
    assert out["registry_gate"]["runner"] == rel


# ---- run_nfl_auto: frozen in the NFL M2 code surface, so it is wrapped --

def test_run_nfl_auto_frozen_file_untouched_and_wrapper_gates(tmp_path, monkeypatch):
    surface = json.loads((ROOT / "config/nfl_m2_code_surface_v1.json").read_text())
    assert "scripts/run_nfl_auto.py" in surface["files"]
    assert "registry_gate" not in (ROOT / "scripts/run_nfl_auto.py").read_text()
    mod = _load("scripts/run_nfl_auto_gated.py")
    out = tmp_path / "nfl.json"
    out.write_text(json.dumps({"status": "SUCCESS", "report": {"rows": [
        {"market": "PLAYER_RECEPTIONS", "model_p": 0.6, "ev": 0.1},
        {"market": "moneyline", "model_p": 0.58}]}}))
    mod.gate_output(out)
    card = json.loads(out.read_text())
    assert not G.is_priced(card["report"]["rows"][0])
    assert card["report"]["rows"][1]["model_p"] == 0.58
    assert card["registry_gate"]["blocked"] == 1


def test_run_nfl_auto_wrapper_unreadable_card_fails_closed(tmp_path):
    mod = _load("scripts/run_nfl_auto_gated.py")
    out = tmp_path / "nfl.json"
    out.write_text("{oops")
    mod.gate_output(out)
    card = json.loads(out.read_text())
    assert card["status"] == "BLOCKED"
    assert card["blocker"].startswith("REGISTRY_GATE_UNREADABLE_CARD")


def test_run_nfl_auto_wrapper_gates_after_frozen_main(tmp_path, monkeypatch):
    mod = _load("scripts/run_nfl_auto_gated.py")
    out = tmp_path / "nfl.json"
    real_spec = importlib.util.spec_from_file_location

    class Fake:
        def main(self):
            assert sys.argv[0] == "scripts/run_nfl_auto.py"
            out.write_text(json.dumps({"rows": [
                {"market": "ANYTIME_TD", "model_p": 0.3}]}))
            return 0

    class Loader:
        def exec_module(self, m):
            m.main = Fake().main

    class Spec:
        loader = Loader()
    monkeypatch.setattr(importlib.util, "spec_from_file_location",
                        lambda *a, **k: Spec())
    monkeypatch.setattr(importlib.util, "module_from_spec",
                        lambda spec: type("M", (), {})())
    assert mod.main(["--output", str(out)]) == 0
    monkeypatch.setattr(importlib.util, "spec_from_file_location", real_spec)
    assert not G.is_priced(json.loads(out.read_text())["rows"][0])
