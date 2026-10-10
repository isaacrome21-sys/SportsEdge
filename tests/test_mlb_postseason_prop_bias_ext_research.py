"""Postseason BB / H / ER / H+W+ER bias check (#1482): parsing, production parity, decision rule, hook."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from sportsedge import mlb_postseason_prop_bias_ext_research as R
from sportsedge import mlb_postseason_prop_bias_research as BASE
from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_pitcher_prior_ext_research import XStart
from sportsedge.pitcher_joint_engine import price_pitcher_market

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pit(ip, k, bb, h, er):
    return {"stats": {"pitching": {"inningsPitched": ip, "strikeOuts": k, "baseOnBalls": bb, "hits": h, "earnedRuns": er}}}


def test_boxscore_takes_first_listed_pitcher_with_bb_h_er():
    box = {"teams": {
        "away": {"team": {"id": 114}, "pitchers": [11, 12],
                 "players": {"ID11": _pit("4.2", 6, 3, 5, 2), "ID12": _pit("3.0", 1, 0, 1, 0)}},
        "home": {"team": {"id": 145}, "pitchers": [21], "players": {"ID21": _pit("6.0", 8, 1, 4, 1)}}}}
    rows = R.starters_from_boxscore(box, game_pk=5, date="2025-10-04", season=2025, game_type="D")
    assert [(r.pitcher_id, r.opp_id, r.outs, r.k, r.bb, r.h, r.er) for r in rows] == [
        (11, 145, 14, 6, 3, 5, 2), (21, 114, 18, 8, 1, 4, 1)]
    assert R.realised(rows[0], "PITCHER_HITS_WALKS_ER") == 10


def test_boxscore_skips_side_with_missing_stat():
    box = {"teams": {"away": {"team": {"id": 114}, "pitchers": [11], "players": {"ID11": {"stats": {"pitching": {
        "inningsPitched": "5.0", "strikeOuts": 4, "hits": 3, "earnedRuns": 1}}}}},
        "home": {"team": {"id": 145}, "pitchers": []}}}
    assert R.starters_from_boxscore(box, game_pk=5, date="2025-10-04", season=2025, game_type="D") == []


def _regular(n_prev=14, n_cur=16, pid=9):
    out = []
    for i in range(n_prev):
        out.append(XStart(pid, 2024, f"2024-{6 + i // 28:02d}-{1 + i % 28:02d}", 1000 + i, 1, 15 + i % 4, 5 + i % 3,
                          i % 4, 3 + i % 5, i % 3))
    for i in range(n_cur):
        out.append(XStart(pid, 2025, f"2025-{6 + i // 28:02d}-{1 + i % 28:02d}", 2000 + i, 1, 14 + i % 6, 4 + i % 5,
                          (i * 3) % 5, 2 + (i * 7) % 6, (i * 5) % 4))
    out.append(XStart(pid, 2023, "2023-07-01", 1, 1, 18, 6, 1, 4, 2))  # outside Y-1..Y
    out.append(XStart(pid + 1, 2025, "2025-06-02", 2, 1, 18, 6, 1, 4, 2))  # other pitcher
    return out


def _target(d="2025-10-05"):
    return R.PStartX(9, 2025, d, 999, "D", 1, 2, 15, 5, 2, 6, 3)


def test_window_split_matches_production_definition():
    own, prior = R.own_and_prior(R.regular_window(_regular(), _target()))
    assert len(own) == 10 and own[-1].date == "2025-06-16" and all(r.pitcher_id == 9 for r in own)
    assert prior is not None and len(prior) == 20
    assert prior[-1] == R.regular_window(_regular(), _target())[-11]
    own2, prior2 = R.own_and_prior(R.regular_window(_regular(0, 13), _target()))
    assert len(own2) == 10 and prior2 is None  # only 3 older starts -> no prior pool
    own3, _ = R.own_and_prior(R.regular_window(_regular(0, 4), _target()))
    assert len(own3) == 4


class _FakeSource(MLBGenericHistorySource):
    """Feeds the production feature builder the same regular-season starts the research uses."""

    def __init__(self, starts):
        super().__init__(opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))
        self.starts = starts

    def player_rows(self, *, player_id, group, target_date):
        rows = []
        for s in self.starts:
            d = date.fromisoformat(s.date)
            if s.pitcher_id == player_id and d < target_date and s.season in (target_date.year - 1, target_date.year):
                ip = f"{s.outs // 3}.{s.outs % 3}"
                rows.append({"date": d, "opponent_id": 2, "game_pk": s.game_pk,
                             "stat": {"gamesStarted": 1, "inningsPitched": ip, "strikeOuts": s.k, "earnedRuns": s.er,
                                      "hits": s.h, "baseOnBalls": s.bb}})
        rows.sort(key=lambda x: x["date"])
        return rows

    def _ump_bb_payload(self, **_kw):
        return None, "lane off in research"


@pytest.mark.parametrize("market", R.MARKETS)
@pytest.mark.parametrize("n_prev,n_cur", [(14, 16), (0, 13), (0, 7)])
def test_features_and_prices_equal_production_feature_builder(market, n_prev, n_cur):
    regular = _regular(n_prev, n_cur)
    target = _target()
    prod = _FakeSource(regular).feature_row(game_pk=999, market=market, entity_id="9", target_date=date(2025, 10, 5),
                                            away_team_id=1, home_team_id=2, player_id=9, team_id=1)
    prod_features = {k: v for k, v in prod["features"].items() if k in ("history_pool", "prior_pool")}
    own, prior = R.own_and_prior(R.regular_window(regular, target))
    mine = R.production_features(own, prior, market)
    assert mine == prod_features
    for line in R.TYPICAL[market]:
        want = price_pitcher_market({"game_id": "g", "market": market, "entity_id": "9", "line": line, "side": "OVER",
                                     "features": prod["features"]})["model_p"]
        assert R.production_p_over(own, prior, market, line) == pytest.approx(want, abs=1e-12, rel=0)


def test_production_features_require_five_starts():
    own, prior = R.own_and_prior(R.regular_window(_regular(0, 4), _target()))
    with pytest.raises(R.PostseasonBiasExtError):
        R.production_features(own, prior, "PITCHER_ER")


def test_build_rows_scores_typical_lines_and_drops_thin_history():
    regular = _regular(14, 16) + _regular(0, 3, pid=50)
    starts = [_target(), R.PStartX(50, 2025, "2025-10-05", 999, "D", 2, 1, 15, 5, 0, 2, 0)]
    rows, drops = R.build_rows(starts, regular)
    assert drops == {"thin_history": 1} and len(rows) == 1
    r = rows[0]
    assert r["y"] == {"PITCHER_BB": 2, "PITCHER_HITS_ALLOWED": 6, "PITCHER_ER": 3, "PITCHER_HITS_WALKS_ER": 11}
    assert [q for _, q in r["pairs"]["PITCHER_ER"]] == [1.0, 1.0, 1.0]
    assert [q for _, q in r["pairs"]["PITCHER_HITS_WALKS_ER"]] == [1.0, 1.0, 1.0, 1.0, 1.0]
    assert all(0 < p < 1 for m in R.MARKETS for p, _ in r["pairs"][m])
    assert r["has_prior_pool"]


def _rows(bias_by_season, n=40):
    rows = []
    for s, b in bias_by_season.items():
        for g in range(n):
            jitter = 0.01 * ((g % 3) - 1)
            pairs = [(0.5 + b + jitter, 1.0), (0.5 + b + jitter, 0.0)] * 2
            rows.append({"season": s, "game_pk": s * 1000 + g, "pairs": {m: pairs for m in R.MARKETS}})
    return rows


def test_decision_is_the_1967_rule():
    d = R.decision(_rows({2022: 0.06, 2023: 0.08, 2024: 0.05, 2025: 0.07}), "PITCHER_ER")
    assert d["guard"] and d["pooled"]["bias"] == pytest.approx(0.065, abs=1e-3)
    d = R.decision(_rows({2022: 0.05, 2023: -0.06, 2024: -0.06, 2025: -0.06}), "PITCHER_BB")
    assert d["rule1_ci_excludes_0"] and d["rule2_material"] and not d["rule3_2022_same_sign"] and not d["guard"]
    d = R.decision(_rows({2022: -0.02, 2023: -0.02, 2024: -0.02, 2025: -0.02}), "PITCHER_HITS_ALLOWED")
    assert not d["rule2_material"] and not d["guard"]


def test_constants_and_prereg_are_frozen():
    assert R.TYPICAL == {"PITCHER_BB": (0.5, 1.5, 2.5), "PITCHER_HITS_ALLOWED": (2.5, 3.5, 4.5, 5.5),
                         "PITCHER_ER": (0.5, 1.5, 2.5), "PITCHER_HITS_WALKS_ER": (2.5, 4.5, 6.5, 8.5, 10.5)}
    assert R.SEASONS == (2022, 2023, 2024, 2025) and R.MIN_ABS_BIAS == 0.03 and R.BOOT_SEED == 20261010
    assert R.POSTSEASON_TYPES == BASE.POSTSEASON_TYPES == ("F", "D", "L", "W")
    text = R.PREREG_PATH.read_text()
    assert "RESEARCH postseason_prop_bias_ext" in text and "|bias| ≥ 0.03" in text
    assert len(R.prereg_sha256()) == 64


def test_intake_hook_registered():
    intake = _load("intake_mlb_lines_issue_psbias_ext", "scripts/intake_mlb_lines_issue.py")
    script = intake.RESEARCH_DIRECTIVES["postseason_prop_bias_ext"]
    assert script == ["scripts/research_mlb_postseason_prop_bias_ext.py"] and (ROOT / script[0]).exists()
