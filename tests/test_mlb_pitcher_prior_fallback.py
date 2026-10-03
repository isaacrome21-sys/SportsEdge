"""Few-starts pitcher prior fallback in production (#1482 B3), validated in #1495.

The engine's fallback prices must equal the research code that passed the
pre-registered held-out test, and the scope must stay exactly what was validated.
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
from sportsedge import mlb_pitcher_prior_research as R
from sportsedge.mlb_empirical_support import empirical_guard_reason, support_evidence
from sportsedge.mlb_generic_features import MLBGenericFeatureError, MLBGenericHistorySource
from sportsedge.pitcher_joint_engine import PitcherJointEngineError, price_pitcher_market

ROOT = Path(__file__).resolve().parents[1]


def _artifact(seed: int = 3, n: int = 600) -> dict:
    rnd = random.Random(seed)
    outs: dict[str, int] = {}
    ks: dict[str, int] = {}
    for _ in range(n):
        o = max(0, min(27, int(rnd.gauss(14, 4))))
        k = max(0, int(rnd.gauss(4, 2)))
        outs[str(o)] = outs.get(str(o), 0) + 1
        ks[str(k)] = ks.get(str(k), 0) + 1
    return {"schema": P.SCHEMA, "pool": "league_short", "season": 2025, "starts": n,
            "counts": {"outs": outs, "strikeouts": ks}}


def _own(k: int, seed: int = 5) -> list[dict[str, int]]:
    rnd = random.Random(seed)
    return [{"strikeouts": rnd.randint(1, 9), "outs": rnd.randint(6, 21), "earned_runs": 2,
             "hits_allowed": 5, "walks_allowed": 2} for _ in range(k)]


@pytest.mark.parametrize("k", [1, 2, 3, 4])
@pytest.mark.parametrize("market,stat,thresholds", [("PITCHER_OUTS", "outs", R.OUTS_THRESH), ("PITCHER_K", "k", R.K_THRESH)])
def test_engine_fallback_equals_validated_research_predict(k, market, stat, thresholds):
    prior = P.validate_artifact(_artifact())
    own = _own(k, seed=k)
    feats = P.fallback_features(own, market, prior)
    # Research side: same own starts, same pool as over-fractions, m = 4.
    own_starts = [R.Start(1, 2026, f"2026-04-0{i + 1}", i, 1, r["outs"], r["strikeouts"]) for i, r in enumerate(own)]
    counts = prior["counts"]
    hist_o = np.zeros(R.OUTS_MAX + 1)
    for v, c in counts["outs"].items():
        hist_o[min(v, R.OUTS_MAX)] += c
    hist_k = np.zeros(R.K_CAP + 1)
    for v, c in counts["strikeouts"].items():
        hist_k[min(v, R.K_CAP)] += c
    pool = {"outs": R._over_frac(hist_o, R.OUTS_THRESH), "k": R._over_frac(hist_k, R.K_THRESH)}
    research = R.predict(own_starts, pool, P.PRIOR_PSEUDO_STARTS)[stat]
    for i, line in enumerate(thresholds):
        for side in ("OVER", "UNDER"):
            out = price_pitcher_market({"market": market, "side": side, "line": float(line), "features": feats})
            expected = research[i] if side == "OVER" else 1 - research[i]
            assert out["model_p"] == pytest.approx(expected, abs=1e-12)
            assert out["meta"]["prior_fallback"]["own_starts"] == k
            assert out["meta"]["effective_history_starts"] == k + 4


def test_engine_scope_is_exactly_what_was_validated():
    prior = P.validate_artifact(_artifact())
    feats = P.fallback_features(_own(2), "PITCHER_OUTS", prior)
    with pytest.raises(PitcherJointEngineError, match="HALF_LINES_ONLY"):
        price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": 15.0, "features": feats})
    with pytest.raises(PitcherJointEngineError, match="NOT_VALIDATED"):
        price_pitcher_market({"market": "PITCHER_ER", "side": "OVER", "line": 2.5, "features": feats})
    with pytest.raises(P.PitcherPriorError):
        P.fallback_features(_own(5), "PITCHER_OUTS", prior)
    with pytest.raises(P.PitcherPriorError):
        P.fallback_features([], "PITCHER_K", prior)
    with pytest.raises(P.PitcherPriorError):
        P.fallback_features(_own(2), "PITCHER_HITS_ALLOWED", prior)
    # Without prior_fallback the original >=5-start rule is unchanged.
    with pytest.raises(PitcherJointEngineError, match="at least 5"):
        price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": 4.5, "features": {"history_pool": _own(3)}})


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


def test_feature_builder_uses_fallback_only_for_validated_cases(tmp_path, monkeypatch):
    (tmp_path / "mlb_pitcher_prior_league_short_2025.json").write_text(json.dumps(_artifact()))
    monkeypatch.setattr(P, "CONFIG_DIR", tmp_path)
    P._load.cache_clear()
    row = _row(_FakeSource(1), "PITCHER_OUTS")
    assert row["joint_feature_version"] == "mlb_pitcher_joint_history_prior_fallback_v1"
    assert len(row["features"]["history_pool"]) == 1 and row["features"]["prior_fallback"]["pseudo_starts"] == 4
    assert _row(_FakeSource(4), "PITCHER_K")["features"]["prior_fallback"]["market"] == "PITCHER_K"
    assert "prior_fallback" not in _row(_FakeSource(6), "PITCHER_K")["features"]  # normal path untouched
    for src, market in ((_FakeSource(0), "PITCHER_OUTS"), (_FakeSource(2), "PITCHER_ER"), (_FakeSource(3), "PITCHER_HITS_ALLOWED")):
        with pytest.raises(MLBGenericFeatureError, match="insufficient chronological sample"):
            _row(src, market)
    P._load.cache_clear()


def test_missing_or_invalid_artifact_keeps_market_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CONFIG_DIR", tmp_path)
    P._load.cache_clear()
    with pytest.raises(MLBGenericFeatureError, match="insufficient chronological sample 2<5"):
        _row(_FakeSource(2), "PITCHER_OUTS")
    (tmp_path / "mlb_pitcher_prior_league_short_2025.json").write_text(json.dumps({"schema": "nope"}))
    P._load.cache_clear()
    with pytest.raises(MLBGenericFeatureError, match="invalid prior artifact"):
        _row(_FakeSource(2), "PITCHER_OUTS")
    P._load.cache_clear()


def test_support_guard_uses_model_tail_not_raw_own_counts():
    prior = P.validate_artifact(_artifact())
    feature = {"features": P.fallback_features(_own(1), "PITCHER_OUTS", prior), "source_subset_hash": "h"}
    out = price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": 14.5, "features": feature["features"]})
    row = {**out, "american_odds": -110}
    row["empirical_evidence"] = support_evidence(feature, row)
    assert row["empirical_evidence"]["prior_fallback"]["own_starts"] == 1
    assert 0.1 < row["model_p"] < 0.9
    assert empirical_guard_reason(row, row["model_p"]) is None  # 1/1 own starts is not a tail by itself
    tail = dict(row, model_p=0.05)
    assert empirical_guard_reason(tail, 0.05).startswith("EMPIRICAL_THIN_TAIL_UNSUPPORTED")


def test_card_note_names_fallback_rows():
    payload = {"results": [
        {"entity_id": "641835", "market": "PITCHER_OUTS", "empirical_evidence": {"prior_fallback": {"own_starts": 2, "pseudo_starts": 4.0, "pool": "league_short", "season": 2025}}},
        {"entity_id": "641835", "market": "PITCHER_OUTS", "empirical_evidence": {"prior_fallback": {"own_starts": 2, "pseudo_starts": 4.0, "pool": "league_short", "season": 2025}}},
        {"entity_id": "661563", "market": "PITCHER_OUTS", "empirical_evidence": {"sample_size": 8}},
    ]}
    notes = P.fallback_notes(payload, {"641835": "Tyler Mahle"})
    assert notes == ["FEW-STARTS PRIOR FALLBACK Tyler Mahle Pitcher Outs: 2 own starts + 4 prior pseudo-starts (league_short 2025, validated #1495). LEAN max."]


def test_pool_artifact_builder_round_trips():
    spec = importlib.util.spec_from_file_location("prior_fb2", ROOT / "scripts/research_mlb_pitcher_prior_fallback.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rnd = random.Random(2)
    starts = []
    for pid in range(1, 200):
        for g in range(rnd.randint(1, 3)):
            starts.append(R.Start(pid, 2025, f"2025-05-{1 + g:02d}", pid * 10 + g, 1, rnd.randint(3, 20), rnd.randint(0, 9)))
    art = mod.build_pool_artifact(starts, 2025)
    assert art["starts"] == len(starts)  # every pitcher here has <5 starts
    checked = P.validate_artifact(json.loads(json.dumps(art)))
    assert sum(checked["counts"]["outs"].values()) == len(starts)


def test_committed_2025_artifact_is_valid_and_used_for_2026_games():
    P._load.cache_clear()
    prior = P.prior_for(date(2026, 10, 3))
    assert prior is not None and prior["season"] == 2025
    assert sum(prior["counts"]["outs"].values()) == sum(prior["counts"]["strikeouts"].values()) == 547
    assert P.prior_for(date(2025, 6, 1)) is None  # no 2024 artifact: 2025 games would stay BLOCKED
