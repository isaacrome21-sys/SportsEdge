"""Grok ruling 2026-10-24a: BET/LEAN/ACTIONABLE display requires an engine status passing is_pick_status."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


png = _load("render_sportsedge_png")
dk = _load("render_auto_dk_phone_summary")
NON_PICK = [None, "", "SOMETHING_UNKNOWN", "WATCH_CFB_MARKET_ONLY_NO_VALIDATED_WEIGHT",
            "WATCH_UNVALIDATED_INJURY_WEATHER_ADJ", "BELOW_THRESHOLD", "BET"]


def _res(label, engine_status):
    r = {"bet_status": label, "scored_status": label, "matchup": "A @ B", "market": "TOTAL", "side": "OVER",
         "line": 50.5, "american_odds": -110, "price_american": -110, "estimate_p": 0.55, "edge": 2.0,
         "expected_roi": 0.05, "ev_per_dollar": 0.05}
    if engine_status is not None:
        r["engine_status"] = engine_status
    return r


def _nfl(engine_status):
    pick = {"selection": "OVER", "line": 44.5, "price_american": -110, "estimate_p": 0.55,
            "edge_probability_points": 2.0, "ev_per_dollar": 0.05}
    if engine_status is not None:
        pick["engine_status"] = engine_status
    return {"games": [{"away": "A", "home": "B", "markets": [{"market": "TOTAL", "pick": pick, "lean": dict(pick)}]}]}


@pytest.mark.parametrize("engine", NON_PICK)
@pytest.mark.parametrize("label", ["ACTIONABLE", "BET", "LEAN", "CANDIDATE"])
def test_png_results_never_best_or_lean_without_pick_engine_status(label, engine):
    rows = png.as_rows({"results": [_res(label, engine)]}, "CFB")
    assert all(r["status"] not in {"BEST", "LEAN", "BET", "ACTIONABLE"} for r in rows)


@pytest.mark.parametrize("engine", NON_PICK)
def test_png_nfl_games_never_best_or_lean_without_pick_engine_status(engine):
    rows = png.as_rows(_nfl(engine), "NFL")
    assert all(r["status"] not in {"BEST", "LEAN"} for r in rows)


def test_png_pick_engine_status_still_displays():
    rows = png.as_rows({"results": [_res("BET", "RESEARCH_POSITIVE_EV_UNVALIDATED")]}, "CFB")
    assert [r["status"] for r in rows] == ["LEAN"]  # PNG path pre-existing: never BEST, max LEAN


@pytest.mark.parametrize("engine", NON_PICK)
@pytest.mark.parametrize("label", ["BET", "LEAN"])
def test_dk_summary_cfb_never_best_or_lean_without_pick_engine_status(label, engine):
    rows = dk.candidates("CFB", {"results": [_res(label, engine)]})
    assert all(r["role"] not in {"BEST", "LEAN"} for r in rows)


@pytest.mark.parametrize("engine", NON_PICK)
def test_dk_summary_nfl_never_best_or_lean_without_pick_engine_status(engine):
    rows = dk.candidates("NFL", _nfl(engine))
    assert all(r["role"] not in {"BEST", "LEAN"} for r in rows)


def test_dk_summary_pick_engine_status_still_displays():
    rows = dk.candidates("CFB", {"results": [_res("BET", "RESEARCH_CANDIDATE_NOT_VALIDATED")]})
    assert [r["role"] for r in rows] == ["BEST"]


@pytest.mark.parametrize("path", ["scripts/render_sportsedge_png.py", "scripts/render_auto_dk_phone_summary.py"])
def test_label_renderers_route_through_is_pick_status(path):
    assert "is_pick_status(" in (ROOT / path).read_text()


def test_ruling_recorded():
    doc = (ROOT / "docs/decisions/GROK_RULINGS_20261024.md").read_text()
    assert "2026-10-24a" in doc and "is_pick_status" in doc
