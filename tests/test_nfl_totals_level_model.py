"""Tests for the NFL totals LEVEL model research candidate.

Covers: module construction against hand-computed values, the
preregistered constants, shrinkage behavior, determinism, and the
evaluator's hash-lock / reproduction machinery on a synthetic
corpus-free path (the full evaluation runs against the manifested
nflverse corpus and is covered by its own locks + precondition).
"""
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sportsedge.research import nfl_totals_level_model as lvl  # noqa: E402

PKG = REPO_ROOT / "research" / "nfl_totals_level_model_20261016"


def test_preregistered_constants():
    assert lvl.KAPPA == 4.0
    assert lvl.LEAGUE_FALLBACK == 22.0
    assert lvl.HFA_HALF == 0.75
    assert lvl.TOTAL_SD == 13.5


def test_league_rate_and_fallback():
    assert lvl.league_rate([]) == 22.0
    # games (away, home): totals 30 and 50 -> 80 pts / 4 team-games
    assert lvl.league_rate([(10, 20), (24, 26)]) == 20.0


def test_shrunk_rate_endpoints():
    # n = 0 -> league exactly; large n -> raw rate approached.
    assert lvl.shrunk_rate(0, 0, 22.0) == 22.0
    assert abs(lvl.shrunk_rate(230, 10, 22.0) - (230 + 88) / 14) < 1e-12


def test_expected_scores_hand_computed():
    league = 22.0
    # Home: 4 games, PF 100, PA 80. Away: 4 games, PF 84, PA 96.
    e_home, e_away = lvl.expected_scores((4, 100, 80), (4, 84, 96), league)
    off_h = (100 + 88) / 8      # 23.5
    def_a = (96 + 88) / 8       # 23.0
    off_a = (84 + 88) / 8       # 21.5
    def_h = (80 + 88) / 8       # 21.0
    assert e_home == pytest.approx((off_h + def_a) / 2 + 0.75)
    assert e_away == pytest.approx((off_a + def_h) / 2 - 0.75)
    # League-average teams split by HFA only.
    eh, ea = lvl.expected_scores((0, 0, 0), (0, 0, 0), league)
    assert eh == pytest.approx(22.75) and ea == pytest.approx(21.25)
    assert lvl.total_mean(eh, ea) == pytest.approx(44.0)


def test_determinism():
    rec_h = lvl.team_record([(27, 20), (24, 17), (31, 28)])
    rec_a = lvl.team_record([(13, 30), (20, 20)])
    first = lvl.expected_scores(rec_h, rec_a, 22.4)
    for _ in range(5):
        assert lvl.expected_scores(rec_h, rec_a, 22.4) == first


def test_prereg_hash_lock_matches_disk():
    locked = {}
    for line in (PKG / "SPEC_HASHES.txt").read_text().splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            locked[name.strip()] = digest
    actual = hashlib.sha256(
        (PKG / "PREREG_NFL_TOTALS_LEVEL_MODEL.md").read_bytes()
    ).hexdigest()
    assert locked["PREREG_NFL_TOTALS_LEVEL_MODEL.md"] == actual


def test_evaluator_refuses_wrong_dataset(tmp_path):
    bogus = tmp_path / "bogus.csv"
    bogus.write_text("season,game_type\n")
    proc = subprocess.run(
        [sys.executable,
         str(PKG / "eval_nfl_totals_level_model.py"),
         "--dataset", str(bogus)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode != 0
    assert "DATASET_SHA256_MISMATCH" in proc.stderr + proc.stdout


def test_evaluator_imports_and_constants():
    sys.path.insert(0, str(PKG))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "eval_lvl", PKG / "eval_nfl_totals_level_model.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.STAGE2["frozen_mean"] == 7.8225
    assert mod.STAGE2["b2_mean"] == 7.7126
    assert mod.EXPECTED_MODEL_BLOB.startswith("253b0c6d")
    # CRPS sanity: a Normal centered on the observation beats one
    # centered far away, symmetric around the mean.
    y = 45
    assert mod.crps_normal(45.0, 13.5, y) < mod.crps_normal(60.0, 13.5, y)
    assert math.isclose(mod.crps_normal(45.0, 13.5, y),
                        mod.crps_normal(45.0, 13.5, 2 * 45 - y),
                        rel_tol=1e-9)
