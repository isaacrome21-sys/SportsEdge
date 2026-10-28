"""Offline guards for the shared CBB forward core
(sportsedge/cbb_torvik_efficiency_v1): construction equivalence with
the construction of record, the R-1 morning-of vintage reader's
named refusals, and the crosswalk/Illinois identity rules.

No network, no pinned data legs: the vintage fixtures are synthetic
stores written under tmp_path, and the equivalence checks compare
arithmetic against the screen modules imported from the research
packages (the pattern of tests/test_cbb_torvik_screen_attempt4.py).
"""

import csv
import hashlib
import importlib.util
import io
import json
import random
from pathlib import Path

import pytest

from sportsedge import cbb_torvik_efficiency_v1 as core
from sportsedge.cbb_torvik_efficiency_v1 import (
    CbbForwardError,
    TeamRatings,
    baseline_team_points,
    candidate_team_points,
    illinois_excluded,
    load_crosswalk,
    load_vintage,
    model_outputs,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


screen = _load_module(
    "run_screen_attempt4",
    "research/cbb_torvik_efficiency_screen_20261028/"
    "run_screen_attempt4.py")
tt_screen = _load_module(
    "cbb_team_totals",
    "research/cbb_team_totals_screen_20261028/cbb_team_totals.py")


# ------------------------------------------------------- construction

def test_candidate_points_match_screen_of_record_exactly():
    rng = random.Random(20261028)
    for _ in range(200):
        home = TeamRatings(rng.uniform(85, 130), rng.uniform(85, 120),
                           rng.uniform(60, 78))
        away = TeamRatings(rng.uniform(85, 130), rng.uniform(85, 120),
                           rng.uniform(60, 78))
        mean_eff = rng.uniform(100, 108)
        fx = {"adj_o_home": home.adj_o, "adj_d_home": home.adj_d,
              "tempo_home": home.adj_tempo, "adj_o_away": away.adj_o,
              "adj_d_away": away.adj_d, "tempo_away": away.adj_tempo,
              "league_mean_eff": mean_eff}
        assert candidate_team_points(home, away, mean_eff) == \
            screen.candidate_points(fx)
        assert candidate_team_points(home, away, mean_eff) == \
            tt_screen.candidate_team_points(fx)


def test_baseline_points_match_screen_of_record_exactly():
    rng = random.Random(20261028)
    for _ in range(200):
        home = TeamRatings(rng.uniform(85, 130), rng.uniform(85, 120),
                           rng.uniform(60, 78))
        away = TeamRatings(rng.uniform(85, 130), rng.uniform(85, 120),
                           rng.uniform(60, 78))
        mean_eff = rng.uniform(100, 108)
        mean_tempo = rng.uniform(66, 70)
        fx = {"adj_o_home": home.adj_o, "adj_d_home": home.adj_d,
              "tempo_home": home.adj_tempo, "adj_o_away": away.adj_o,
              "adj_d_away": away.adj_d, "tempo_away": away.adj_tempo,
              "league_mean_eff": mean_eff,
              "league_mean_tempo": mean_tempo}
        assert baseline_team_points(home, away, mean_eff,
                                    mean_tempo) == \
            screen.baseline_points(fx)
        assert baseline_team_points(home, away, mean_eff,
                                    mean_tempo) == \
            tt_screen.simple_baseline_team_points(fx)


def test_model_outputs_match_screen_margin_and_total_forms():
    home = TeamRatings(118.0, 92.0, 68.0)
    away = TeamRatings(116.0, 94.0, 67.0)
    out = model_outputs(home, away, 104.0, 68.5, neutral_site=False)
    cand_home, cand_away = candidate_team_points(home, away, 104.0)
    # The screen's forms, exactly: margin = points difference + hc
    # term; total = points sum (the hc term never enters points).
    assert out["model_margin_home_candidate"] == (
        cand_home - cand_away) + core.HOME_COURT_CANDIDATE_FORWARD
    assert out["model_total_candidate"] == cand_home + cand_away
    assert out["expected_points_home_candidate"] == cand_home
    neutral = model_outputs(home, away, 104.0, 68.5, neutral_site=True)
    assert neutral["home_court_term_candidate"] == 0.0
    assert neutral["model_margin_home_candidate"] == \
        cand_home - cand_away
    assert neutral["model_total_candidate"] == cand_home + cand_away


def test_forward_constants_are_the_recorded_fit():
    assert core.HOME_COURT_CANDIDATE_FORWARD == 3.260655725219634
    assert core.HOME_COURT_BASELINE_FIXED == 3.3756023216238145
    assert core.SEED == 20261028


# ------------------------------------------------------------ vintage

def _vintage_csv_bytes(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "team", "conf", "record", "adjoe", "oe Rank",
                "adjde", "de Rank", "barthag", "adjt"])
    for i, (team, o, d, t) in enumerate(rows, 1):
        w.writerow([i, team, "X", "0-0", o, 1, d, 1, 0.5, t])
    return buf.getvalue().encode("utf-8")


def _write_store(tmp_path, date="2026-11-02", rows=None, **manifest_kw):
    if rows is None:
        rows = [("Duke", 118.0, 92.0, 68.0),
                ("Kansas", 116.0, 94.0, 67.0)]
        rows += [(f"Filler {i:03d}", 100.0, 100.0, 68.0)
                 for i in range(320)]
    raw = _vintage_csv_bytes(rows)
    store = tmp_path / "torvik_morning"
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{date}.csv").write_bytes(raw)
    manifest = {"season_year": 2027, "as_of_local_date": date,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "team_rows": len(rows),
                "evidence_state": "verified-by-pull"}
    manifest.update(manifest_kw)
    (store / f"{date}.json").write_text(json.dumps(manifest))
    return store


def test_vintage_happy_path_league_means_over_file_as_published(
        tmp_path):
    store = _write_store(tmp_path)
    v = load_vintage("2026-11-02", store)
    assert v.by_team["Duke"] == TeamRatings(118.0, 92.0, 68.0)
    assert v.team_rows == 322
    expected_eff = (118.0 + 116.0 + 320 * 100.0) / 322
    assert v.league_mean_eff == expected_eff
    assert v.league_mean_tempo == (68.0 + 67.0 + 320 * 68.0) / 322


def test_vintage_missing_pair_refuses(tmp_path):
    store = tmp_path / "empty"
    store.mkdir()
    with pytest.raises(CbbForwardError) as exc:
        load_vintage("2026-11-02", store)
    assert exc.value.reason == "TORVIK_VINTAGE_MISSING"


def test_vintage_manifest_refusal_refuses(tmp_path):
    store = _write_store(tmp_path, refusal="LATE_PULL")
    with pytest.raises(CbbForwardError) as exc:
        load_vintage("2026-11-02", store)
    assert exc.value.reason == "TORVIK_VINTAGE_UNAVAILABLE"


def test_vintage_date_mismatch_refuses(tmp_path):
    store = _write_store(tmp_path)
    with pytest.raises(CbbForwardError) as exc:
        load_vintage("2026-11-03", store)
    assert exc.value.reason == "TORVIK_VINTAGE_MISSING"
    # A vintage filed under one date but attesting another is the
    # mismatch case: R-1 never substitutes a neighboring date.
    (store / "2026-11-03.csv").write_bytes(
        (store / "2026-11-02.csv").read_bytes())
    (store / "2026-11-03.json").write_bytes(
        (store / "2026-11-02.json").read_bytes())
    with pytest.raises(CbbForwardError) as exc:
        load_vintage("2026-11-03", store)
    assert exc.value.reason == "TORVIK_VINTAGE_DATE_MISMATCH"


def test_vintage_late_pull_flag_refuses(tmp_path):
    store = _write_store(
        tmp_path,
        snapshot_warning="LATE_PULL: pulled after 10:00 local; valid "
                           "as prior-snapshot input for later dates "
                           "only")
    with pytest.raises(CbbForwardError) as exc:
        load_vintage("2026-11-02", store)
    assert exc.value.reason == "TORVIK_VINTAGE_LATE_PULL"


def test_vintage_hash_mismatch_refuses(tmp_path):
    store = _write_store(tmp_path)
    csv_path = store / "2026-11-02.csv"
    csv_path.write_bytes(csv_path.read_bytes() + b"\n")
    with pytest.raises(CbbForwardError) as exc:
        load_vintage("2026-11-02", store)
    assert exc.value.reason == "TORVIK_VINTAGE_HASH_MISMATCH"


def test_vintage_schema_invalid_refuses(tmp_path):
    rows = [("Duke", 118.0, 92.0, 68.0)] + [
        (f"Filler {i:03d}", 100.0, 100.0, 68.0) for i in range(50)]
    store = _write_store(tmp_path, rows=rows)  # only 51 teams
    with pytest.raises(CbbForwardError) as exc:
        load_vintage("2026-11-02", store)
    assert exc.value.reason == "TORVIK_VINTAGE_SCHEMA_INVALID"


# ----------------------------------------------------------- identity

def test_crosswalk_resolves_and_illinois_rule_matches_scope():
    cw = load_crosswalk(
        ROOT / "research/cbb_identity_crosswalk_20261028/"
        "crosswalk.json")
    duke = cw.for_espn_id("150")
    assert duke.canonical_id == "duke" and duke.torvik_name == "Duke"
    illinois = cw.for_espn_id("356")
    assert illinois.canonical_id == "illinois"
    assert illinois_excluded(illinois, "356") is True
    assert illinois_excluded(duke, "150") is False
    # Fail-closed on the denylist even without a crosswalk entry, and
    # on institution state (the scope module's rule).
    assert illinois_excluded(None, "356") is True
    assert illinois_excluded(duke, "150", "IL") is True
    assert cw.for_espn_id("999999999") is None
