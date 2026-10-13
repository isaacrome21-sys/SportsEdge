"""Source and valuation tests for #2156 (requested in ChatGPT review 6147917889).

Source: the parsers run against a real, trimmed MLB Stats API capture
(tests/fixtures/mlb_statsapi_sample_20261013.json), not only synthetic dicts.
Valuation: probabilities are coherent, agree with brute-force enumeration and
the frozen full-game model, and carry no market/odds/edge fields.
"""
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sportsedge import mlb_f5_team_total_ladder as m
from sportsedge.mlb_either_pitcher_asof import parse_pitcher_gamelog
from sportsedge.mlb_either_pitcher_walkforward import build_events
from sportsedge.mlb_f5_walkforward import parse_schedule
from sportsedge.v7_distribution import calibrated_full_game_means

FX = json.loads((Path(__file__).parent / "fixtures" / "mlb_statsapi_sample_20261013.json").read_text())
MARKET_KEYS = {"odds", "price", "american", "decimal", "edge", "ev", "vig", "no_vig", "market_p", "implied"}


# ---------------- source ----------------
def test_schedule_parse_real_capture_f5_and_regulation_consistent():
    games = parse_schedule([FX["schedule"]])
    assert len(games) == 2
    for g, raw in zip(sorted(games, key=lambda g: g["game_id"]),
                      sorted(FX["schedule"]["dates"][0]["games"], key=lambda g: g["gamePk"])):
        inn = raw["linescore"]["innings"]
        assert g["away_f5"] == sum(int(i["away"].get("runs", 0)) for i in inn[:5])
        assert g["away_runs"] == raw["teams"]["away"]["score"]
        assert g["away_f5"] <= g["away_reg"] <= g["away_runs"]  # F5 subset of regulation
        assert g["start"].tzinfo is not None and g["status"] == "FINAL"


def test_schedule_parse_dedupes_and_rejects_non_final_real_shape():
    g0 = FX["schedule"]["dates"][0]["games"][0]
    dup = {"dates": [{"date": "x", "games": [g0, g0, dict(g0, gamePk=1, status={"codedGameState": "I"}),
                                             dict(g0, gamePk=2, gameType="S"), dict(g0, gamePk=3, gameDate="bad")]}]}
    assert [g["game_id"] for g in parse_schedule([dup])] == [g0["gamePk"]]


def test_gamelog_parse_real_capture():
    for pid, payload in FX["gamelogs"].items():
        rows = parse_pitcher_gamelog(payload)
        raw = payload["stats"][0]["splits"]
        assert len(rows) == len(raw)
        for r, s in zip(rows, raw):
            assert r["game_pk"] == s["game"]["gamePk"]
            assert r["hits"] == s["stat"]["hits"] and r["earnedRuns"] == s["stat"]["earnedRuns"]
            assert r["started"] == (s["stat"]["gamesStarted"] == 1)


def test_events_bind_probables_to_actual_starts_real_capture():
    logs = {int(p): parse_pitcher_gamelog(v) for p, v in FX["gamelogs"].items()}
    ev = build_events([FX["schedule"]], logs)
    assert len(ev) == 2
    for e in ev:
        assert e["away"] is not None and e["home"] is not None
        assert e["away"]["game_pk"] == e["game_pk"] == e["home"]["game_pk"]
    # dropping one starter's log must mark that event as not-started (excluded), never mis-bind
    some = next(iter(logs))
    ev2 = build_events([FX["schedule"]], {k: v for k, v in logs.items() if k != some})
    assert sum(e["away"] is None or e["home"] is None for e in ev2) == 1


# ---------------- valuation ----------------
@pytest.mark.parametrize("away,home,share", [(3.9, 5.2, 0.55), (4.5, 4.5, 0.6), (6.0, 3.1, 0.5)])
def test_f5_ladder_coherent_with_full_game_model(away, home, share):
    out = m.price_f5_team_totals({"away_mean_runs": away, "home_mean_runs": home, "f5_share": share,
                                  "lines": [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5]})
    ca, ch = calibrated_full_game_means(away, home)
    for side, mu in (("AWAY", ca), ("HOME", ch)):
        t = out["teams"][side]
        assert t["full_game_mean"] == pytest.approx(mu)
        assert t["f5_mean"] == pytest.approx(share * mu) and t["f5_mean"] < mu
        pmf = m.nb_pmf(share * mu)
        assert sum(k * p for k, p in enumerate(pmf)) == pytest.approx(share * mu, rel=1e-3)
        prev = 1.0
        for row in t["ladder"]:
            assert row["over"] + row["under"] + row["push"] == pytest.approx(1.0, abs=1e-12)
            assert 0 <= row["over"] <= prev + 1e-12
            prev = row["over"]
            if float(row["line"]).is_integer():
                assert row["push"] == pytest.approx(pmf[int(row["line"])])
            else:
                assert row["push"] == 0
                assert row["over"] == pytest.approx(sum(pmf[int(row["line"]) + 1:]))
    assert not MARKET_KEYS & set(json.dumps(out).lower().replace('"', " ").split())


def test_zinb_candidate_valuation_coherent():
    out = m.price_f5_team_totals({"away_mean_runs": 4.4, "home_mean_runs": 4.6, "f5_share": 0.57,
                                  "f5_dispersion_r": 2.5, "f5_zero_inflation": 0.06, "lines": [0.5, 1, 1.5]})
    base = m.price_f5_team_totals({"away_mean_runs": 4.4, "home_mean_runs": 4.6, "f5_share": 0.57,
                                   "lines": [0.5, 1, 1.5]})
    for side in ("AWAY", "HOME"):
        z, b = out["teams"][side]["ladder"], base["teams"][side]["ladder"]
        assert z[0]["over"] < b[0]["over"]  # more zero mass -> lower P(>0.5)
        assert all(abs(r["over"] + r["under"] + r["push"] - 1) < 1e-12 for r in z)


def test_either_pitcher_ladder_matches_brute_force_enumeration():
    a = [0.05, 0.1, 0.2, 0.25, 0.2, 0.1, 0.06, 0.04]
    b = [0.1, 0.15, 0.25, 0.2, 0.15, 0.1, 0.05]
    lines = [1.5, 2, 3.5, 5, 6.5]
    out = m.either_pitcher_ladder(a, b, lines)
    for row, x in zip(out["ladder"], lines):
        over = sum(pa * pb for (i, pa), (j, pb) in itertools.product(enumerate(a), enumerate(b)) if max(i, j) > x)
        push = sum(pa * pb for (i, pa), (j, pb) in itertools.product(enumerate(a), enumerate(b)) if max(i, j) == x)
        assert row["over"] == pytest.approx(over) and row["push"] == pytest.approx(push)
        assert row["over"] + row["under"] + row["push"] == pytest.approx(1.0)
    # max-of-two dominates each single pitcher
    for row, x in zip(out["ladder"], lines):
        assert row["over"] >= sum(p for k, p in enumerate(a) if k > x) - 1e-12
    assert out["settlement_status"] == "UNVERIFIED_DK_RULES" and out["market_baseline"] == "MISSING"


def test_valuation_outputs_never_grade_or_authorize():
    s = m.settle_f5_team_total(team_f5_runs=3, line=2.5, side="OVER", completed_innings=9)
    assert s["grade"] is None and s["authoritative"] is False
    out = m.price_f5_team_totals({"away_mean_runs": 4, "home_mean_runs": 4, "f5_share": .55})
    assert out["play_authority"] is False and out["status"] == "RESEARCH_ONLY"
