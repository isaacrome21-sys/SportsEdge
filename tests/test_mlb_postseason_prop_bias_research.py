"""Postseason PITCHER_K / PITCHER_OUTS bias check (#1482): parsing, production parity, decision rule, hook."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_opp_k_context as LANE_K
from sportsedge import mlb_opp_outs_context as LANE_O
from sportsedge import mlb_postseason_prop_bias_research as R
from sportsedge.mlb_opp_k_context_research import KStart, OppIndex, predict_k
from sportsedge.mlb_opp_outs_context_research import OStart, predict_outs

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_schedule_keeps_final_postseason_games_only():
    payload = {"dates": [{"date": "2025-10-01", "games": [
        {"gamePk": 1, "gameType": "F", "officialDate": "2025-10-01", "status": {"abstractGameState": "Final"}},
        {"gamePk": 2, "gameType": "R", "officialDate": "2025-10-01", "status": {"abstractGameState": "Final"}},
        {"gamePk": 3, "gameType": "D", "officialDate": "2025-10-01", "status": {"abstractGameState": "Preview"}},
        {"gamePk": 1, "gameType": "F", "officialDate": "2025-10-01", "status": {"abstractGameState": "Final"}},
    ]}, {"date": "2025-10-20", "games": [
        {"gamePk": 9, "gameType": "W", "status": {"abstractGameState": "Final"}}]}]}
    assert R.final_postseason_games(payload) == [(1, "2025-10-01", "F"), (9, "2025-10-20", "W")]


def test_boxscore_takes_first_listed_pitcher_per_side():
    box = {"teams": {
        "away": {"team": {"id": 114}, "pitchers": [11, 12],
                 "players": {"ID11": {"stats": {"pitching": {"inningsPitched": "4.2", "strikeOuts": 6}}},
                             "ID12": {"stats": {"pitching": {"inningsPitched": "3.0", "strikeOuts": 1}}}}},
        "home": {"team": {"id": 145}, "pitchers": [21],
                 "players": {"ID21": {"stats": {"pitching": {"inningsPitched": "6.0", "strikeOuts": 8}}}}}}}
    rows = R.starters_from_boxscore(box, game_pk=5, date="2025-10-04", season=2025, game_type="D")
    assert [(r.pitcher_id, r.team_id, r.opp_id, r.outs, r.k) for r in rows] == [(11, 114, 145, 14, 6), (21, 145, 114, 18, 8)]


def test_boxscore_skips_side_without_stats():
    box = {"teams": {"away": {"team": {"id": 114}, "pitchers": [11], "players": {}},
                     "home": {"team": {"id": 145}, "pitchers": []}}}
    assert R.starters_from_boxscore(box, game_pk=5, date="2025-10-04", season=2025, game_type="D") == []


def _team_games(seasons, n_games, k_rate=0.22):
    out = {}
    for s in seasons:
        for t in range(1, 31):
            rate = k_rate * (1 + 0.01 * (t - 15))
            out[(t, s)] = [(f"{s}-05-{1 + d % 28:02d}" if d < 28 else f"{s}-06-{1 + d % 28:02d}", int(round(38 * rate)), 38)
                           for d in range(n_games)]
    return out


def test_lanes_follow_production_prior_season_rule():
    full = _team_games((2021, 2022, 2023), 120)
    assert R.lanes_allowed(full, 2023)
    short = _team_games((2020,), 60) | _team_games((2021, 2022), 120)
    assert not R.lanes_allowed(short, 2022)
    assert R.season_indices(short, short, 2022) is None
    assert LANE_K.MIN_PRIOR_SEASON_GAMES == LANE_O.MIN_PRIOR_SEASON_GAMES == 100


def _history(n=10):
    k = [KStart(7, 2025, f"2025-08-{d + 1:02d}", 100 + d, 1, 2 + d % 5, 4 + d % 4) for d in range(n)]
    o = [OStart(7, 2025, r.date, r.game_pk, r.team_id, r.opp_id, 15 + r.game_pk % 4) for r in k]
    return k, o


def test_production_prices_equal_research_predict_functions():
    games = _team_games((2023, 2024, 2025), 120)
    idx = R.season_indices(games, games, 2025)
    assert idx is not None
    k, o = _history()
    target = R.PStart(7, 2025, "2025-10-05", 999, "D", 1, 9, 12, 5)
    got = R.production_prices(k, o, target, idx)
    kt = KStart(7, 2025, "2025-10-05", 999, 1, 9, 5)
    ot = OStart(7, 2025, "2025-10-05", 999, 1, 9, 12)
    np.testing.assert_allclose(got["PITCHER_K"], predict_k(k, kt, idx[0], LANE_K.BETA), atol=1e-12, rtol=0)
    np.testing.assert_allclose(got["PITCHER_OUTS"], predict_outs(o, ot, {LANE_O.INDEX: idx[1]}, (LANE_O.INDEX, LANE_O.BETA)),
                               atol=1e-12, rtol=0)
    off = R.production_prices(k, o, target, None)
    np.testing.assert_allclose(off["PITCHER_K"], predict_k(k, kt, OppIndex({}), 0.0), atol=1e-12, rtol=0)
    assert LANE_K.BETA == 1.0 and LANE_O.BETA == -0.25 and LANE_O.INDEX == "obidx"


def test_production_prices_require_five_starts():
    k, o = _history(4)
    with pytest.raises(R.PostseasonBiasError):
        R.production_prices(k, o, R.PStart(7, 2025, "2025-10-05", 999, "D", 1, 9, 12, 5), None)


def test_own_history_uses_last_ten_prior_regular_starts_in_window():
    k = [KStart(7, 2024, f"2024-07-{d + 1:02d}", d, 1, 2, 5) for d in range(8)]
    k += [KStart(7, 2025, f"2025-08-{d + 1:02d}", 50 + d, 1, 2, 5) for d in range(6)]
    k += [KStart(7, 2023, "2023-07-01", 1000, 1, 2, 5), KStart(8, 2025, "2025-08-03", 2000, 1, 2, 5)]
    own = R.own_history(k, R.PStart(7, 2025, "2025-08-05", 1, "D", 1, 2, 0, 0))
    assert len(own) == 10 and own[-1].date == "2025-08-04" and all(r.pitcher_id == 7 and r.season >= 2024 for r in own)


def _rows(bias_by_season, n=40):
    rows = []
    for s, b in bias_by_season.items():
        for g in range(n):
            jitter = 0.01 * ((g % 3) - 1)
            pairs = [(0.5 + b + jitter, 1.0), (0.5 + b + jitter, 0.0)] * 2
            rows.append({"season": s, "game_pk": s * 1000 + g, "pairs": {"PITCHER_K": pairs, "PITCHER_OUTS": pairs}})
    return rows


def test_decision_guards_material_consistent_bias():
    d = R.decision(_rows({2022: 0.06, 2023: 0.08, 2024: 0.05, 2025: 0.07}), "PITCHER_OUTS")
    assert d["pooled"]["bias"] == pytest.approx(0.065, abs=1e-3)
    assert d["rule1_ci_excludes_0"] and d["rule2_material"] and d["rule3_2022_same_sign"] and d["guard"]


def test_decision_needs_unseen_2022_sign():
    d = R.decision(_rows({2022: -0.02, 2023: 0.1, 2024: 0.1, 2025: 0.1}), "PITCHER_K")
    assert d["rule1_ci_excludes_0"] and d["rule2_material"] and not d["rule3_2022_same_sign"] and not d["guard"]


def test_decision_needs_materiality():
    d = R.decision(_rows({2022: 0.02, 2023: 0.02, 2024: 0.02, 2025: 0.02}), "PITCHER_K")
    assert not d["rule2_material"] and not d["guard"]


def test_bootstrap_is_deterministic_and_game_clustered():
    rows = _rows({2022: 0.05, 2023: -0.01, 2024: 0.04, 2025: 0.0}, n=10)
    a, b = R.bootstrap_bias(rows, "PITCHER_K"), R.bootstrap_bias(rows, "PITCHER_K")
    assert a == b and a["games"] == 40 and a["lo"] <= a["bias"] <= a["hi"]


def test_typical_lines_and_prereg_are_frozen():
    assert R.TYPICAL == {"PITCHER_K": (3.5, 4.5, 5.5, 6.5), "PITCHER_OUTS": (14.5, 15.5, 16.5, 17.5)}
    assert R.SEASONS == (2022, 2023, 2024, 2025) and R.MIN_ABS_BIAS == 0.03 and R.BOOT_SEED == 20261010
    text = R.PREREG_PATH.read_text()
    assert "RESEARCH postseason_prop_bias" in text and "|bias| ≥ 0.03" in text
    assert len(R.prereg_sha256()) == 64


def test_intake_hook_registered():
    intake = _load("intake_mlb_lines_issue_psbias", "scripts/intake_mlb_lines_issue.py")
    assert intake.RESEARCH_DIRECTIVES["postseason_prop_bias"] == ["scripts/research_mlb_postseason_prop_bias.py"]
    assert (ROOT / intake.RESEARCH_DIRECTIVES["postseason_prop_bias"][0]).exists()
