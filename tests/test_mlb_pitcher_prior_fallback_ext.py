"""Few-starts fallback extension to PITCHER_BB / HITS_ALLOWED / ER in production (#1482).

Held-out PASS in #1943 (pre-registration docs/MLB_PITCHER_PRIOR_FALLBACK_EXT_PREREG.md).
Engine prices must equal the research code that passed, and the scope must stay
exactly what was validated: k = 1..4, half lines inside the scored range, frozen
pool only, H+W+ER and EITHER_PITCHER still BLOCKED.
"""
from __future__ import annotations

import importlib.util
import json
import random
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_pitcher_prior as P
from sportsedge import mlb_pitcher_prior_ext_research as X
from sportsedge.mlb_generic_features import MLBGenericFeatureError, MLBGenericHistorySource
from sportsedge.pitcher_joint_engine import PitcherJointEngineError, price_pitcher_market

ROOT = Path(__file__).resolve().parents[1]
STAT_OF = {"PITCHER_BB": ("bb", "walks_allowed"), "PITCHER_HITS_ALLOWED": ("h", "hits_allowed"), "PITCHER_ER": ("er", "earned_runs")}


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _short_starts(seed: int = 3, n: int = 600) -> list[X.XStart]:
    rnd = random.Random(seed)
    return [X.XStart(i + 1, 2025, "2025-05-01", i + 1, 1, max(0, min(27, int(rnd.gauss(14, 4)))), max(0, int(rnd.gauss(4, 2))),
                     max(0, int(rnd.gauss(2, 1.5))), max(0, int(rnd.gauss(5, 2.5))), max(0, int(rnd.gauss(2.5, 2))))
            for i in range(n)]


def _artifacts(starts=None):
    runner = _load("prior_ext_runner_prod", "scripts/research_mlb_pitcher_prior_fallback_ext.py")
    ext = runner.build_ext_pool_artifact(starts or _short_starts(), 2025)
    base = {"schema": P.SCHEMA, "pool": "league_short", "season": 2025, "starts": ext["starts"],
            "counts": {"outs": ext["counts"]["outs"], "strikeouts": ext["counts"]["strikeouts"]}}
    return base, ext


def _own(k: int, seed: int = 5) -> list[dict[str, int]]:
    rnd = random.Random(seed)
    return [{"strikeouts": rnd.randint(1, 9), "outs": rnd.randint(6, 21), "earned_runs": rnd.randint(0, 6),
             "hits_allowed": rnd.randint(1, 10), "walks_allowed": rnd.randint(0, 5)} for _ in range(k)]


@pytest.mark.parametrize("k", [1, 2, 3, 4])
@pytest.mark.parametrize("market", sorted(STAT_OF))
def test_engine_equals_validated_research_predict_fallback(k, market):
    starts = _short_starts()
    base_raw, ext_raw = _artifacts(starts)
    ext = P.validate_ext_artifact(ext_raw, P.validate_artifact(base_raw))
    own = _own(k, seed=10 * k)
    feats = P.fallback_features(own, market, ext)
    stat, key = STAT_OF[market]
    # Research side: the #1943 code path, pool built from the same starts the artifact was built from.
    window = __import__("sportsedge.mlb_pitcher_prior_research", fromlist=["x"]).prior_window_counts(starts)
    pool = X.league_short_pool(starts, window)
    own_x = [X.XStart(1, 2026, f"2026-04-0{i + 1}", i + 1, 1, r["outs"], r["strikeouts"], r["walks_allowed"], r["hits_allowed"], r["earned_runs"])
             for i, r in enumerate(own)]
    research = X.predict_fallback(own_x, pool)[stat]
    for i, line in enumerate(X.THRESH[stat]):
        for side in ("OVER", "UNDER"):
            out = price_pitcher_market({"market": market, "side": side, "line": float(line), "features": feats})
            expected = research[i] if side == "OVER" else 1 - research[i]
            assert out["model_p"] == pytest.approx(expected, abs=1e-12)
            assert out["meta"]["prior_fallback"]["own_starts"] == k
            assert out["meta"]["effective_history_starts"] == k + 4
    assert [r[key] for r in feats["history_pool"]] == [r[key] for r in own]


def test_scope_is_exactly_what_was_validated():
    base_raw, ext_raw = _artifacts()
    ext = P.validate_ext_artifact(ext_raw, P.validate_artifact(base_raw))
    feats = P.fallback_features(_own(2), "PITCHER_BB", ext)
    with pytest.raises(PitcherJointEngineError, match="HALF_LINES_ONLY"):
        price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": 1.0, "features": feats})
    for market, line in (("PITCHER_BB", 10.5), ("PITCHER_HITS_ALLOWED", 15.5), ("PITCHER_ER", 12.5)):
        f = P.fallback_features(_own(2), market, ext)
        with pytest.raises(PitcherJointEngineError, match="OUTSIDE_VALIDATED_RANGE"):
            price_pitcher_market({"market": market, "side": "OVER", "line": line, "features": f})
    # Top scored line still prices.
    price_pitcher_market({"market": "PITCHER_ER", "side": "UNDER", "line": 11.5, "features": P.fallback_features(_own(2), "PITCHER_ER", ext)})
    with pytest.raises(PitcherJointEngineError, match="NOT_VALIDATED"):
        price_pitcher_market({"market": "PITCHER_HITS_WALKS_ER", "side": "OVER", "line": 6.5, "features": feats})
    with pytest.raises(P.PitcherPriorError):
        P.fallback_features(_own(2), "PITCHER_HITS_WALKS_ER", ext)
    with pytest.raises(P.PitcherPriorError):
        P.fallback_features(_own(5), "PITCHER_ER", ext)
    with pytest.raises(P.PitcherPriorError):
        P.fallback_features([], "PITCHER_ER", ext)
    # The base (outs/K-only) artifact cannot price BB/H/ER.
    with pytest.raises(P.PitcherPriorError, match="no walks counts"):
        P.fallback_features(_own(2), "PITCHER_BB", P.validate_artifact(base_raw))
    # Without prior_fallback the original >=5-start rule is unchanged for BB/H/ER.
    with pytest.raises(PitcherJointEngineError, match="at least 5"):
        price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": 1.5, "features": {"history_pool": _own(3)}})


def test_ext_artifact_must_be_the_same_pool_as_base():
    base_raw, ext_raw = _artifacts()
    base = P.validate_artifact(base_raw)
    bad = json.loads(json.dumps(ext_raw))
    first = next(iter(bad["counts"]["outs"]))
    bad["counts"]["outs"][first] += 1
    with pytest.raises(P.PitcherPriorError, match="differ from base"):
        P.validate_ext_artifact(bad, base)
    bad = json.loads(json.dumps(ext_raw))
    bad["season"] = 2024
    with pytest.raises(P.PitcherPriorError, match="season"):
        P.validate_ext_artifact(bad, base)
    bad = json.loads(json.dumps(ext_raw))
    del bad["counts"]["hits"]
    with pytest.raises(P.PitcherPriorError, match="hits missing"):
        P.validate_ext_artifact(bad, base)


class _FakeSource(MLBGenericHistorySource):
    def __init__(self, n_starts: int):
        super().__init__(opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))
        self.n = n_starts

    def player_rows(self, *, player_id, group, target_date):
        return [{"date": date(2026, 4, 1 + i), "stat": {"gamesStarted": 1, "inningsPitched": "5.1", "strikeOuts": 5,
                 "earnedRuns": 2, "hits": 4, "baseOnBalls": 1}} for i in range(self.n)]


def _row(src, market):
    return src.feature_row(game_pk=1, market=market, entity_id="9", target_date=date(2026, 10, 3),
                           away_team_id=1, home_team_id=2, player_id=9)


def _write(tmp_path, base_raw=None, ext_raw=None):
    if base_raw is not None:
        (tmp_path / "mlb_pitcher_prior_league_short_2025.json").write_text(json.dumps(base_raw))
    if ext_raw is not None:
        (tmp_path / "mlb_pitcher_prior_league_short_ext_2025.json").write_text(json.dumps(ext_raw))


def _clear():
    P._load.cache_clear()
    P._load_ext.cache_clear()


def test_feature_builder_uses_ext_pool_for_bb_h_er(tmp_path, monkeypatch):
    base_raw, ext_raw = _artifacts()
    _write(tmp_path, base_raw, ext_raw)
    monkeypatch.setattr(P, "CONFIG_DIR", tmp_path)
    _clear()
    for market, stat in (("PITCHER_BB", "walks"), ("PITCHER_HITS_ALLOWED", "hits"), ("PITCHER_ER", "earned_runs")):
        row = _row(_FakeSource(2), market)
        fb = row["features"]["prior_fallback"]
        assert row["joint_feature_version"] == "mlb_pitcher_joint_history_prior_fallback_v1"
        assert fb["market"] == market and fb["pseudo_starts"] == 4
        assert fb["counts"] == {str(k): v for k, v in sorted((int(a), b) for a, b in ext_raw["counts"][stat].items())}
    # Outs/K keep using the base artifact (identity unchanged by the extension).
    assert _row(_FakeSource(2), "PITCHER_K")["features"]["prior_fallback"]["artifact_sha256"] == P.validate_artifact(base_raw)["sha256"]
    # Normal path untouched; k=0 and H+W+ER stay BLOCKED.
    assert "prior_fallback" not in _row(_FakeSource(6), "PITCHER_ER")["features"]
    for src, market in ((_FakeSource(0), "PITCHER_BB"), (_FakeSource(2), "PITCHER_HITS_WALKS_ER")):
        with pytest.raises(MLBGenericFeatureError, match="insufficient chronological sample"):
            _row(src, market)
    _clear()


def test_missing_or_mismatched_ext_artifact_keeps_bb_h_er_blocked(tmp_path, monkeypatch):
    base_raw, ext_raw = _artifacts()
    monkeypatch.setattr(P, "CONFIG_DIR", tmp_path)
    _write(tmp_path, base_raw)  # base only: Outs/K fallback works, BB/H/ER stay BLOCKED
    _clear()
    assert "prior_fallback" in _row(_FakeSource(2), "PITCHER_OUTS")["features"]
    with pytest.raises(MLBGenericFeatureError, match="insufficient chronological sample 2<5"):
        _row(_FakeSource(2), "PITCHER_BB")
    bad = json.loads(json.dumps(ext_raw))
    bad["counts"]["strikeouts"][next(iter(bad["counts"]["strikeouts"]))] += 1
    _write(tmp_path, ext_raw=bad)
    _clear()
    with pytest.raises(MLBGenericFeatureError, match="invalid prior artifact"):
        _row(_FakeSource(2), "PITCHER_ER")
    assert "prior_fallback" in _row(_FakeSource(2), "PITCHER_K")["features"]  # base lane unaffected
    _clear()


def test_card_note_cites_the_right_validation():
    fb = {"own_starts": 1, "pseudo_starts": 4.0, "pool": "league_short", "season": 2025}
    payload = {"results": [
        {"entity_id": "1", "market": "PITCHER_BB", "empirical_evidence": {"prior_fallback": fb}},
        {"entity_id": "1", "market": "PITCHER_OUTS", "empirical_evidence": {"prior_fallback": fb}},
    ]}
    notes = P.fallback_notes(payload, {"1": "Hagen Smith"})
    assert notes == [
        "FEW-STARTS PRIOR FALLBACK Hagen Smith Pitcher BB: 1 own starts + 4 prior pseudo-starts (league_short 2025, validated #1943). LEAN max.",
        "FEW-STARTS PRIOR FALLBACK Hagen Smith Pitcher Outs: 1 own starts + 4 prior pseudo-starts (league_short 2025, validated #1495). LEAN max.",
    ]


def test_emit_pool_builder_and_base_cross_check(tmp_path):
    runner = _load("prior_ext_runner_emit", "scripts/research_mlb_pitcher_prior_fallback_ext.py")
    rnd = random.Random(4)
    starts, gpk = [], 0
    for season in (2024, 2025):
        for pid in range(1, 220):
            for g in range(rnd.randint(1, 7)):
                gpk += 1
                starts.append(X.XStart(pid, season, f"{season}-05-{1 + g:02d}", gpk, 1, rnd.randint(3, 20), rnd.randint(0, 9),
                                       rnd.randint(0, 5), rnd.randint(0, 10), rnd.randint(0, 7)))
    art = runner.build_ext_pool_artifact(starts, 2025)
    expected = [s for s in starts if s.season == 2025 and sum(1 for r in starts if r.pitcher_id == s.pitcher_id and r.date < s.date) < 5]
    assert art["starts"] == len(expected)
    for name in ("outs", "strikeouts", "walks", "hits", "earned_runs"):
        assert sum(art["counts"][name].values()) == len(expected)
    base = {"schema": P.SCHEMA, "pool": "league_short", "season": 2025, "starts": art["starts"],
            "counts": {"outs": art["counts"]["outs"], "strikeouts": art["counts"]["strikeouts"]}}
    P.validate_ext_artifact(json.loads(json.dumps(art)), P.validate_artifact(base))
    (tmp_path / "mlb_pitcher_prior_league_short_2025.json").write_text(json.dumps(base))
    assert runner.base_cross_check(art, tmp_path).startswith("MATCHES")
    base["starts"] += 1
    (tmp_path / "mlb_pitcher_prior_league_short_2025.json").write_text(json.dumps(base))
    assert runner.base_cross_check(art, tmp_path).startswith("MISMATCH")


def test_intake_has_pool_directive():
    intake = _load("mlb_intake_ext_pool", "scripts/intake_mlb_lines_issue.py")
    assert intake.RESEARCH_DIRECTIVES["pitcher_prior_pool_ext"] == ["scripts/research_mlb_pitcher_prior_fallback_ext.py", "--emit-pool", "2025"]
    assert intake.research_directive("RESEARCH pitcher_prior_pool_ext") == "pitcher_prior_pool_ext"


def test_no_ext_artifact_committed_yet_means_bb_h_er_blocked_in_repo():
    """Until the frozen 2025 ext pool is emitted in Actions and committed, production BB/H/ER stay BLOCKED."""
    _clear()
    ext_path = P.ext_artifact_path(2025)
    prior = P.prior_for(date(2026, 10, 3), market="PITCHER_BB")
    if ext_path.exists():
        assert prior is not None and prior["season"] == 2025
        assert set(prior["counts"]) == {"outs", "strikeouts", "walks", "hits", "earned_runs"}
    else:
        assert prior is None
    assert P.prior_for(date(2026, 10, 3), market="PITCHER_K") is not None
    _clear()
