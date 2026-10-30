"""Tests for sportsedge.nfl_prop_engines_v1 (Oct 20 2026 build):
the research engines for the registered NFL prop families that
resolved NO_ENGINE.  Per family: point-in-time discipline, the
sufficiency (role-gate) refusal, and a priced example with sane
probability bounds; plus registry tests that building the engines
changed no family's registration state or eligibility."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sportsedge import nfl_prop_engines_v1 as eng
from sportsedge.canonical_coverage import resolve_market
from sportsedge.nfl_family_registry_v2 import REGISTRY_V2

RESULTS = (Path(__file__).resolve().parents[1] / "research"
           / "nfl_prop_engines_20261020" / "screen_results_v1.json")

BUILT = ("pass_plus_rush_yards", "rush_plus_rec_yards", "targets",
         "two_plus_td", "fg_made", "xp_made", "kicking_points",
         "player_sacks", "tackles_assists", "player_interceptions")
NOT_BUILT = ("longest_completion", "longest_rush", "longest_reception",
             "interceptions", "first_td", "passing_yards",
             "rushing_yards", "rush_yards", "receiving_yards",
             "receptions", "rush_attempts", "attempts", "completions",
             "passing_tds", "anytime_td")


def mkrow(**kw):
    row = {k: 0.0 for k in eng.RAW_COLUMNS}
    row.update({k: float(v) for k, v in kw.items()})
    return eng._derive(row)


def season_of(players):
    """players: {pid: (position, [weekly row kwargs])} -> season dict."""
    return {pid: [(w + 1, pos, mkrow(**games[w]))
                  for w in range(len(games))]
            for pid, (pos, games) in players.items()}


def wr_targets(tlist):
    return ("WR", [dict(targets=t, receptions=5, receiving_yards=60,
                        carries=1, rushing_yards=5) for t in tlist])


# ---------------------------------------------------------------- PIT

def test_pit_priors_exclude_priced_week_and_future():
    players = {f"W{i}": wr_targets([8] * 8) for i in range(6)}
    players["W0"] = wr_targets([8, 8, 8, 8, 8, 8, 99, 8])  # wk7 spike
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop("targets", "W0", 7.5, data, 2024, 6)
    assert out["status"] == "PRICED"
    assert out["games_logged"] == 5
    assert out["prior_values"] == [8.0] * 5
    assert out["mu"] == pytest.approx(8.0)  # (5*8 + 3*8) / 8
    assert out["pool_mean"] == pytest.approx(8.0)


def test_pit_pool_excludes_same_week_outcomes():
    players = {f"W{i}": wr_targets([8] * 8) for i in range(6)}
    players["W1"] = wr_targets([8, 8, 8, 8, 8, 99, 8, 8])  # wk6 = priced wk
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop("targets", "W0", 7.5, data, 2024, 6)
    assert out["pool_mean"] == pytest.approx(8.0)  # the 99 never enters


# ------------------------------------------------------- sufficiency

def test_sufficiency_too_few_prior_games():
    players = {"NEW": wr_targets([9, 9])}
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop("targets", "NEW", 7.5, data, 2024, 3)
    assert out["status"] == "NOT_QUALIFIED"
    assert out["reason"] == "ONLY_2_PRIOR_GAMES"
    assert "p_over" not in out


def test_sufficiency_role_mean_below_threshold():
    players = {"LOW": wr_targets([2] * 8)}
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop("targets", "LOW", 7.5, data, 2024, 6)
    assert out["status"] == "NOT_QUALIFIED"
    assert out["reason"].startswith("ROLE_MEAN_2.00_BELOW_4")


def test_qb_gate_for_pass_plus_rush():
    gadget = ("WR", [dict(attempts=25, passing_yards=200,
                          rushing_yards=30, carries=3) for _ in range(8)])
    qb = ("QB", [dict(attempts=32, passing_yards=250, rushing_yards=20,
                      carries=4) for _ in range(8)])
    data = {2024: season_of({"GADGET": gadget, "QB1": qb})}
    out = eng.price_nfl_prop("pass_plus_rush_yards", "GADGET", 260.5,
                             data, 2024, 6)
    assert out["status"] == "NOT_QUALIFIED"
    assert out["reason"] == "NOT_QB"


def test_unbuilt_family_refuses_to_price():
    data = {2024: season_of({"W0": wr_targets([8] * 8)})}
    with pytest.raises(ValueError, match="NFL_PROP_ENGINE_FAMILY_UNKNOWN"):
        eng.price_nfl_prop("interceptions", "W0", 0.5, data, 2024, 6)
    with pytest.raises(ValueError, match="NFL_PROP_ENGINE_FAMILY_UNKNOWN"):
        eng.price_nfl_prop("longest_rush", "W0", 12.5, data, 2024, 6)


# --------------------------------------------------- priced examples

HEALTHY = dict(attempts=32, passing_yards=250, rushing_yards=60,
               receiving_yards=70, targets=9, carries=12, receptions=6,
               rushing_tds=1, receiving_tds=1, fg_att=2, fg_made=2,
               pat_att=3, pat_made=3, def_sacks=1, def_interceptions=1,
               def_tackles_solo=4, def_tackle_assists=2)


@pytest.mark.parametrize("family,line", [
    ("pass_plus_rush_yards", 285.5), ("rush_plus_rec_yards", 115.5),
    ("targets", 8.5), ("fg_made", 1.5), ("xp_made", 2.5),
    ("kicking_points", 8.5), ("player_sacks", 0.5),
    ("tackles_assists", 5.5), ("player_interceptions", 0.5),
])
def test_priced_example_sane_bounds(family, line):
    players = {f"P{i}": ("QB" if family == "pass_plus_rush_yards"
                         else "LB", [HEALTHY] * 8) for i in range(6)}
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop(family, "P0", line, data, 2024, 6)
    assert out["status"] == "PRICED", out
    assert 0.0 < out["p_over"] < 1.0
    assert out["p_push"] == 0.0
    assert out["p_over"] + out["p_under"] + out["p_push"] == \
        pytest.approx(1.0)
    assert out["fair_probability_basis"] == "CONDITIONAL_ON_NON_PUSH"
    assert out["games_logged"] == 5
    assert 0.0 < out["shrink_weight"] < 1.0


def test_integer_count_line_preserves_push_instead_of_assigning_it_under():
    players = {f"P{i}": ("WR", [HEALTHY] * 8) for i in range(6)}
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop("targets", "P0", 9.0, data, 2024, 6)
    assert out["status"] == "PRICED"
    assert out["p_push"] > 0.0
    assert out["p_under"] < 1.0 - out["p_over"]
    assert out["p_over"] + out["p_push"] + out["p_under"] == \
        pytest.approx(1.0)
    nonpush = out["p_over"] + out["p_under"]
    assert out["fair_over_american"] == pytest.approx(
        eng.fair_american(out["p_over"] / nonpush))
    assert out["fair_under_american"] == pytest.approx(
        eng.fair_american(out["p_under"] / nonpush))


def test_integer_continuous_yardage_line_has_no_artificial_push():
    players = {f"P{i}": ("QB", [HEALTHY] * 8) for i in range(6)}
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop(
        "pass_plus_rush_yards", "P0", 310.0, data, 2024, 6)
    assert out["status"] == "PRICED"
    assert out["p_push"] == 0.0
    assert out["p_over"] + out["p_under"] == pytest.approx(1.0)


def test_two_plus_td_yes_only_contract():
    players = {f"RB{i}": ("RB", [HEALTHY] * 8) for i in range(6)}
    data = {2024: season_of(players)}
    out = eng.price_nfl_prop("two_plus_td", "RB0", 0.0, data, 2024, 6,
                             offer_form="YES_ONLY")
    assert out["status"] == "PRICED"
    assert out["line"] == 1.5  # P(>= 2 TDs) is P(stat > 1.5)
    assert 0.0 < out["p_yes"] < 1.0
    grid = __import__("numpy").arange(eng.GRID_LO, eng.GRID_HI + 1,
                                      dtype=float)
    expect = eng.p_over_for(out["mu"], out["cv"], True, 1.5, grid)
    assert out["p_yes"] == pytest.approx(expect)
    with pytest.raises(ValueError, match="OFFER_FORM_UNSUPPORTED"):
        eng.price_nfl_prop("two_plus_td", "RB0", 1.5, data, 2024, 6,
                           offer_form="TWO_SIDED_OU")


def test_prior_season_pool_fallback():
    old = {f"D{i}": ("DE", [dict(def_sacks=1, def_tackles_solo=4,
                                 def_tackle_assists=2)] * 10)
           for i in range(5)}
    new = {f"D{i}": ("DE", [dict(def_sacks=1, def_tackles_solo=4,
                                 def_tackle_assists=2)] * 5)
           for i in range(5)}
    data = {2024: season_of(old), 2025: season_of(new)}
    out = eng.price_nfl_prop("player_sacks", "D0", 0.5, data, 2025, 4)
    assert out["status"] == "PRICED"  # pool fell back to 2024 outcomes
    assert out["pool_mean"] == pytest.approx(1.0)


# ------------------------------------------------- loader discipline

def _write_csv(path, fieldnames, rows):
    import csv as _csv
    import gzip as _gz
    with _gz.open(path, "wt") as fh:
        w = _csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_loader_column_presence_no_zero_fill(tmp_path):
    ps_fields = ["player_id", "position", "season", "week", "season_type",
                 "attempts", "passing_yards", "carries", "rushing_yards",
                 "targets", "receptions", "receiving_yards"]
    ps_rows = [dict(player_id="K1", position="K", season=2024, week=w,
                    season_type="REG", attempts=0, passing_yards=0,
                    carries=0, rushing_yards=0, targets=0, receptions=0,
                    receiving_yards=0) for w in range(1, 9)]
    _write_csv(tmp_path / "ps_2024.csv.gz", ps_fields, ps_rows)
    sp_fields = ps_fields + ["fg_made", "fg_att", "pat_made", "pat_att"]
    sp_rows = [dict(player_id="K1", position="K", season=2025, week=w,
                    season_type="REG", attempts=0, passing_yards=0,
                    carries=0, rushing_yards=0, targets=9, receptions=5,
                    receiving_yards=60, fg_made=2, fg_att=2, pat_made=3,
                    pat_att=3) for w in range(1, 9)]
    _write_csv(tmp_path / "sp_2025.csv.gz", sp_fields, sp_rows)
    data = eng.load_player_data(tmp_path)
    # the ps file has no kicking columns: 2024 contributes no FG rows
    out24 = eng.price_nfl_prop("fg_made", "K1", 1.5, data, 2024, 6)
    assert out24["status"] == "NOT_QUALIFIED"
    assert out24["reason"] == "ONLY_0_PRIOR_GAMES"
    # the sp file carries the columns: the same player prices in 2025
    out25 = eng.price_nfl_prop("fg_made", "K1", 1.5, data, 2025, 6)
    assert out25["games_logged"] == 5
    assert out25["status"] in ("PRICED", "NOT_PRICED")  # pool may be thin
    assert out25["status"] != "NOT_QUALIFIED"


def test_loader_preserves_missing_cells_in_present_columns_as_missing(tmp_path):
    fields = ["player_id", "position", "season", "week", "season_type",
              "targets", "receptions", "receiving_yards"]
    target_values = ["8", "", "not-a-number", "8", "0", "8", "8"]
    rows = [dict(player_id="W1", position="WR", season=2024, week=w,
                 season_type="REG", targets=target, receptions=4,
                 receiving_yards=40)
            for w, target in enumerate(target_values, 1)]
    _write_csv(tmp_path / "ps_2024.csv.gz", fields, rows)
    data = eng.load_player_data(tmp_path)
    by_week = {week: stats for week, _, stats in data[2024]["W1"]}
    assert by_week[2]["targets"] is None
    assert by_week[3]["targets"] is None
    assert by_week[5]["targets"] == 0.0  # explicitly recorded zero is real
    family_games = eng.family_view(data, eng.FAMILIES["targets"])[2024]["W1"]
    assert [week for week, _, _ in family_games] == [1, 4, 5, 6, 7]


def test_loader_missing_kicker_stat_propagates_through_derived_points(tmp_path):
    fields = ["player_id", "position", "season", "week", "season_type",
              "fg_made", "fg_att", "pat_made", "pat_att"]
    rows = [dict(player_id="K1", position="K", season=2025, week=w,
                 season_type="REG", fg_made=fg, fg_att=2,
                 pat_made=3, pat_att=3)
            for w, fg in [(1, ""), (2, "0"), (3, "2")]]
    _write_csv(tmp_path / "sp_2025.csv.gz", fields, rows)
    data = eng.load_player_data(tmp_path)
    by_week = {week: stats for week, _, stats in data[2025]["K1"]}
    assert by_week[1]["fg_made"] is None
    assert by_week[1]["kicking_points"] is None
    assert by_week[2]["fg_made"] == 0.0
    assert by_week[2]["kicking_points"] == 3.0
    assert by_week[3]["kicking_points"] == 9.0


# ------------------------------------------------------------ registry

def test_registry_states_unchanged_and_engine_pointers():
    fams = REGISTRY_V2["families"]
    assert len(fams) == 25
    for name, fam in fams.items():
        assert fam["status"] == "RESEARCH_ONLY", name
        assert fam["registration_state"] == "REGISTERED_RESEARCH_ONLY"
        assert fam["promotable"] is False, name
        assert fam["eligible"] is False, name
        assert fam["validation_status"] == "NOT_VALIDATED", name
        assert ("engine" in fam) == (name in BUILT), name
    assert fams["two_plus_td"]["engine_screen"]["verdict"] == \
        "DOES_NOT_BEAT_BASELINE"
    assert fams["targets"]["engine_screen"]["verdict"] == \
        "CALIBRATED_CANDIDATE"
    assert fams["fg_made"]["engine_screen"]["verdict"] == \
        "SCREEN_NOT_RUNNABLE_SANCTIONED_VINTAGE"


def test_canonical_coverage_still_blocked_for_all_registered():
    for name in REGISTRY_V2["families"]:
        res = resolve_market("NFL", name)
        assert res["state"] == "BLOCKED", name
        assert res["state"] != "PRICED_PATH", name


def test_engine_cvs_match_screen_results():
    results = json.loads(RESULTS.read_text())
    for name in BUILT:
        r = results["families"][name]
        screened = r.get("cv") or (r.get("diagnostic") or {}).get("cv")
        assert eng.FAMILIES[name]["cv"] == pytest.approx(screened), name
