"""RED-first tests for the owner-approved NFL V2 safety re-lock (#2265, t212u).

V1 frozen files stay byte-identical; V2 is a separately versioned forward
identity that validates complete probability mass before sampling/pricing and
never renormalizes. V2 has NO forward evidence until a new approved freeze.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

V1_FROZEN_SHA256 = {
    "sportsedge/sports/nfl/market_context_props.py": "b20728a3ccf09b943370f7e3745b528742c525aa837aadf00c4498f94c6619a3",
    "sportsedge/nfl_unified_phone.py": "4fe6c0f5b762d5f8b0afabc738fdaf2d75ddef43095228e0b8b0b0e92dd238b3",
    "sportsedge/sports/nfl/unified_run_it.py": "d7061725baa85a9e156413a35df5685ea30cd0167c08f84a68d1c6971efd495c",
    "sportsedge/sports/nfl/unified_auto_roles.py": "103c096c2dba231af4f51aa3d120fbffa124cf081888f2a4c050ec55e0013e17",
    "sportsedge/sports/nfl/unified_market_engine.py": "ec83bf2353f70bcaaa4f123cb984ed9b246d668fce224e21f879f1f006f1a44d",
    "sportsedge/sports/nfl/live_role_source.py": "763e654affffa2d808f36870c265d99bb209d6e1d1b3a98c778367ee453c4576",
    "sportsedge/sports/nfl/nflverse_role_bridge.py": "c6baa0da7793f6205f2a8cc079aab36caa243d35d6c265857d3eabc6b798836c",
}


def test_v1_frozen_files_byte_identical():
    for rel, digest in V1_FROZEN_SHA256.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
    lock = json.loads((ROOT / "config/research/nfl_market_context_prop_v1_2026_forward_lock.json").read_text())
    assert {r["path"] for r in lock["candidate_identity"]["code_surface"]} == set(V1_FROZEN_SHA256)


def _v2():
    from sportsedge.sports.nfl import unified_market_engine_v2 as v2
    return v2


def test_v2_is_separate_versioned_identity_with_no_evidence_until_freeze():
    v2 = _v2()
    from sportsedge.sports.nfl import unified_market_engine as v1
    assert v2.SCHEMA != v1.SCHEMA and v2.SCHEMA.endswith("_V2")
    assert v2.FORWARD_IDENTITY["engine_version"] == "NFL_UNIFIED_MARKET_ENGINE_V2"
    assert v2.FORWARD_IDENTITY["replaces_v1"] is False
    assert v2.FORWARD_IDENTITY["forward_evidence_status"] == "NO_EVIDENCE_UNTIL_NEW_APPROVED_FREEZE"
    assert v2.FORWARD_IDENTITY["frozen"] is False
    rec = json.loads((ROOT / "config/research/nfl_unified_engine_v2_safety_relock.json").read_text())
    assert rec["status"] == "UNFROZEN_NO_FORWARD_EVIDENCE"
    assert rec["v2_evidence_starts"] == "ONLY_AFTER_NEW_OWNER_APPROVED_FREEZE"
    assert rec["v1_forward_records_altered"] is False
    assert rec["v1_frozen_sha256"] == V1_FROZEN_SHA256


GOOD = [[0.25, 0.25], [0.25, 0.25]]


@pytest.mark.parametrize("grid,code", [
    ([[0.25, 0.25], [0.25, float("nan")]], "SCORE_GRID_NONFINITE"),
    ([[0.25, 0.25], [0.25, float("inf")]], "SCORE_GRID_NONFINITE"),
    ([[0.5, 0.5], [0.25, -0.25]], "SCORE_GRID_NEGATIVE"),
    ([[0.25, 0.25], [0.25, 0.20]], "SCORE_GRID_MASS_NOT_ONE"),
    ([[0.5, 0.5], [0.5, 0.5]], "SCORE_GRID_MASS_NOT_ONE"),
    ([[0.25, 0.25], [0.25, True]], "SCORE_GRID_NONNUMERIC"),
    ([[0.25, 0.25], [0.25, "0.25"]], "SCORE_GRID_NONNUMERIC"),
    ([], "SCORE_GRID_EMPTY"),
    ([[0.0, 0.0]], "SCORE_GRID_EMPTY"),
])
def test_v2_refuses_malformed_grids_before_sampling_and_pricing(grid, code):
    v2 = _v2()
    for call in (
        lambda: v2.validate_score_grid(grid),
        lambda: v2.sample_score_paths(grid, n_sims=10, seed=1),
        lambda: v2.price_game_market(grid, {"market": "moneyline", "selection": "home"}),
    ):
        with pytest.raises(v2.UnifiedNflV2GridError) as exc:
            call()
        assert code in str(exc.value)


def test_v2_short_mass_is_not_masked_where_v1_would_mask():
    from sportsedge.sports.nfl import unified_market_engine as v1
    short = [[0.1, 0.1], [0.1, 0.1]]
    assert len(v1.sample_score_paths(short, n_sims=5, seed=3)) == 5  # V1 masks via cumulative[-1]=1.0
    v2 = _v2()
    with pytest.raises(v2.UnifiedNflV2GridError, match="SCORE_GRID_MASS_NOT_ONE"):
        v2.sample_score_paths(short, n_sims=5, seed=3)


def test_v2_valid_grid_matches_v1_exactly_and_does_not_rescale():
    from sportsedge.sports.nfl import unified_market_engine as v1
    v2 = _v2()
    assert v2.sample_score_paths(GOOD, n_sims=50, seed=7) == v1.sample_score_paths(GOOD, n_sims=50, seed=7)
    req = {"market": "total", "selection": "over", "line": 0.5}
    assert v2.price_game_market(GOOD, req)["estimate_p"] == v1.price_game_market(GOOD, req)["estimate_p"]
    snap = [row[:] for row in GOOD]
    v2.validate_score_grid(GOOD)
    assert GOOD == snap


def test_v2_guarded_score_grid_validates_frozen_shape():
    v2 = _v2()
    grid = v2.guarded_score_grid(24.0, 21.0)
    assert math.isclose(sum(map(sum, grid)), 1.0, abs_tol=v2.MASS_TOLERANCE)


def test_v2_run_unified_refuses_corrupt_grid(monkeypatch):
    v2 = _v2()
    monkeypatch.setattr(v2, "score_grid", lambda h, a, f=None: [[0.2, 0.2], [0.2, 0.2]])
    with pytest.raises(v2.UnifiedNflV2GridError, match="SCORE_GRID_MASS_NOT_ONE"):
        v2.run_unified_nfl_model(game_id="g", home_team="KC", away_team="BUF",
                                 attempt9_margin=3.0, attempt9_total=45.0, n_sims=10)


def test_v2_run_it_entry_guards_the_v1_run_it_resample(monkeypatch):
    """unified_run_it.py:334 is frozen; V2 entry must validate the same grid first."""
    v2 = _v2()
    called = []
    monkeypatch.setattr(v2, "score_grid", lambda h, a, f=None: [[0.2, 0.2], [0.2, 0.2]])
    monkeypatch.setattr(v2, "_v1_run_unified_nfl_run_it", lambda **kw: called.append(kw))
    with pytest.raises(v2.UnifiedNflV2GridError):
        v2.run_unified_nfl_run_it(game_id="g", home_team="KC", away_team="BUF",
                                  attempt9_margin=3.0, attempt9_total=45.0)
    assert called == []


# Direct bypass scan -------------------------------------------------------
V1_ENGINE = "sportsedge.sports.nfl.unified_market_engine"
BYPASS_NAMES = ("sample_score_paths", "price_game_market", "run_unified_nfl_model", "_flat_grid")
FROZEN_V1_ALLOWED = set(V1_FROZEN_SHA256)
V2_MODULE = "sportsedge/sports/nfl/unified_market_engine_v2.py"
# Freeze/prereg-registered grid producers or evaluators: they build a grid but
# do not sample or price through the engine; touching them would change a
# registered identity. Listed explicitly so new callers cannot hide here.
SCORE_GRID_ALLOWED = FROZEN_V1_ALLOWED | {
    V2_MODULE,
    "sportsedge/sports/nfl/discrete_v2.py",
    "sportsedge/sports/nfl/discrete_v2_eval.py",
    "sportsedge/sports/nfl/location_symmetric_g1.py",
    "sportsedge/sports/nfl/location_g1_distribution_readout.py",
}


def _py_files():
    for base in ("sportsedge", "scripts"):
        yield from (ROOT / base).rglob("*.py")


def test_no_direct_v1_engine_bypass_callers_remain():
    offenders = []
    for path in _py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in FROZEN_V1_ALLOWED or rel == V2_MODULE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"unified_market_engine\b(?!_v2)", text) and any(
            re.search(rf"\b{name}\b", text) for name in BYPASS_NAMES
        ):
            offenders.append(rel)
    assert offenders == []


def test_no_unguarded_score_grid_consumers_remain():
    offenders = []
    for path in _py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in SCORE_GRID_ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?<![\w.])score_grid\s*\(", text) or re.search(r"import[^\n]*\bscore_grid\b", text):
            offenders.append(rel)
    assert offenders == []
