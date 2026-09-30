import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "render_mlb_myspari_card", Path("scripts/render_mlb_myspari_card.py")
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)

PRIOR_1256 = {
    "rows": [
        {"game_pk": 849841, "game_id": "Philadelphia Phillies@Atlanta Braves", "market_type": "MONEYLINE", "side": "AWAY", "line": 0, "price": -117},
        {"game_pk": 849841, "game_id": "Philadelphia Phillies@Atlanta Braves", "market_type": "MONEYLINE", "side": "HOME", "line": 0, "price": -103},
        {"game_pk": 849846, "game_id": "Chicago White Sox@Houston Astros", "market_type": "MONEYLINE", "side": "AWAY", "line": 0, "price": 128},
        {"game_pk": 849846, "game_id": "Chicago White Sox@Houston Astros", "market_type": "MONEYLINE", "side": "HOME", "line": 0, "price": -155},
        {"game_pk": 849848, "game_id": "Boston Red Sox@New York Yankees", "market_type": "TOTALS", "side": "OVER", "line": 6.5, "price": -124},
        {"game_pk": 849848, "game_id": "Boston Red Sox@New York Yankees", "market_type": "TOTALS", "side": "UNDER", "line": 6.5, "price": 103},
    ]
}

CURRENT_1273 = {
    "rows": [
        {"game_pk": 849841, "game_id": "Philadelphia Phillies@Atlanta Braves", "market_type": "MONEYLINE", "side": "AWAY", "line": 0, "price": 152},
        {"game_pk": 849841, "game_id": "Philadelphia Phillies@Atlanta Braves", "market_type": "MONEYLINE", "side": "HOME", "line": 0, "price": -180},
        {"game_pk": 849846, "game_id": "Chicago White Sox@Houston Astros", "market_type": "MONEYLINE", "side": "AWAY", "line": 0, "price": 128},
        {"game_pk": 849846, "game_id": "Chicago White Sox@Houston Astros", "market_type": "MONEYLINE", "side": "HOME", "line": 0, "price": -155},
        {"game_pk": 849848, "game_id": "Boston Red Sox@New York Yankees", "market_type": "TOTALS", "side": "OVER", "line": 8.5, "price": -118},
        {"game_pk": 849848, "game_id": "Boston Red Sox@New York Yankees", "market_type": "TOTALS", "side": "UNDER", "line": 8.5, "price": -104},
    ]
}


def _engine() -> dict:
    return {
        "observed_at_utc": "2026-09-30T10:47:51+00:00",
        "results": [],
        "games": [
            {"resolved_game": {"game_pk": 849841, "away_team": "Philadelphia Phillies", "home_team": "Atlanta Braves", "scheduled_start_utc": "2026-09-30T18:00:00+00:00"}},
            {"resolved_game": {"game_pk": 849846, "away_team": "Chicago White Sox", "home_team": "Houston Astros", "scheduled_start_utc": "2026-09-30T21:00:00+00:00"}},
            {"resolved_game": {"game_pk": 849848, "away_team": "Boston Red Sox", "home_team": "New York Yankees", "scheduled_start_utc": "2026-10-01T00:00:00+00:00"}},
        ],
    }


def _card_rows() -> list[dict]:
    return [
        {"game_id": "849841", "market": "MONEYLINE", "side": "AWAY", "line": 0, "american_odds": 152, "status": "ACTIONABLE", "scored_status": "ACTIONABLE"},
        {"game_id": "849848", "market": "TOTALS", "side": "OVER", "line": 8.5, "american_odds": -118, "status": "ACTIONABLE", "scored_status": "ACTIONABLE"},
        {"game_id": "849846", "market": "MONEYLINE", "side": "AWAY", "line": 0, "american_odds": 128, "status": "ACTIONABLE", "scored_status": "ACTIONABLE"},
    ]


def test_render_flags_1273_misreads_against_1256(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prior = tmp_path / "2026-09-30_issue1256.json"
    current = tmp_path / "2026-09-30_issue1273.json"
    engine = tmp_path / "engine.json"
    out = tmp_path / "card"
    prior.write_text(json.dumps(PRIOR_1256))
    current.write_text(json.dumps(CURRENT_1273))
    engine.write_text(json.dumps(_engine()))
    monkeypatch.setattr(MOD, "myspari_rows", lambda *args, **kwargs: _card_rows())
    monkeypatch.setattr(
        "sys.argv",
        [
            "render_mlb_myspari_card.py",
            "--engine-output", str(engine),
            "--snapshot", str(current),
            "--prior-snapshot", str(prior),
            "--out-dir", str(out),
            "--as-of", "2026-09-30T10:48:00+00:00",
        ],
    )
    assert MOD.main() == 0
    text = (out / "card.md").read_text()
    payload = json.loads((out / "card.json").read_text())
    by_key = {(str(r["game_id"]), r["market"]): r for r in payload["rows"]}
    assert by_key[("849841", "MONEYLINE")]["scored_status"] == "NEEDS_CONFIRM"
    assert by_key[("849848", "TOTALS")]["scored_status"] == "NEEDS_CONFIRM"
    assert by_key[("849846", "MONEYLINE")]["scored_status"] == "ACTIONABLE"
    assert "NEEDS_CONFIRM" in text
    assert "screenshot-misread" in text
