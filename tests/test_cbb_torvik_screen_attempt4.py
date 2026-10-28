"""Offline guards for the CBB_TORVIK_EFFICIENCY_V1 screen ATTEMPT 4
runner (Amendment 1 prior-snapshot convention).

These tests never touch the network and never read the pinned data
legs. They pin the attempt-4 mechanics that differ from attempt 3:
the D-1 date arithmetic (never a substitution chain), the
prior-snapshot file parsing (a file is addressed by its OWN date;
a drift-layout file without adj_tempo parses to None = NO_DATA),
the prior-snapshot witness probe (passes on the D-1 values
Amendment 1 declares, fails on any other), and the unchanged
construction/bootstrap arithmetic the screen's criteria rest on.
"""

import csv
import importlib.util
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = (ROOT / "research" / "cbb_torvik_efficiency_screen_20261028"
               / "run_screen_attempt4.py")

_spec = importlib.util.spec_from_file_location("run_screen_attempt4",
                                               RUNNER_PATH)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


# ---------------------------------------------------------- D-1 dates

def test_prior_date_is_exactly_one_day_before():
    assert runner.prior_date_iso("2014-11-14") == "2014-11-13"
    assert runner.prior_date_iso("2023-03-12") == "2023-03-11"
    assert runner.prior_date_iso("2022-11-07") == "2022-11-06"


def test_prior_date_crosses_month_and_year_boundaries():
    assert runner.prior_date_iso("2023-03-01") == "2023-02-28"
    assert runner.prior_date_iso("2020-03-01") == "2020-02-29"  # leap
    assert runner.prior_date_iso("2015-01-01") == "2014-12-31"


# ------------------------------------------------------ file parsing

def _torvik_csv(rows, file_date):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "team", "conf", "record", "barthag", "adj_o",
                "adj_o_rk", "adj_d", "adj_d_rk", "adj_tempo",
                "adj_tempo_rk", "proj_record", "proj_conf_record",
                "wab", "wab_rk", "date"])
    for i, (team, adj_o, adj_d, tempo) in enumerate(rows, 1):
        w.writerow([i, team, "X", "0-0", 0.9, adj_o, 1, adj_d, 1,
                    tempo, 1, "20-10", "10-5", 0.0, 1, file_date])
    return buf.getvalue().encode("utf-8")


_RESOLVE = {"Duke": "duke", "Kansas": "kansas"}.get


def test_parse_reads_the_file_by_its_own_date():
    raw = _torvik_csv([("Duke", 110.0, 90.0, 70.0),
                       ("Kansas", 108.0, 92.0, 68.0)], "2014-11-13")
    parsed = runner.parse_torvik(raw, "2014-11-13", _RESOLVE)
    assert parsed is not None
    assert parsed["by_slug"]["duke"] == (110.0, 90.0, 70.0)
    assert parsed["league_mean_eff"] == 109.0
    assert parsed["league_mean_tempo"] == 69.0
    assert parsed["team_rows"] == 2


def test_parse_refuses_a_file_whose_rows_carry_another_date():
    raw = _torvik_csv([("Duke", 110.0, 90.0, 70.0)], "2014-11-14")
    # Asked for the 2014-11-13 prior snapshot, handed the 11-14 file:
    # a date mismatch is a refusal (None), never a silent acceptance.
    assert runner.parse_torvik(raw, "2014-11-13", _RESOLVE) is None


def test_parse_drift_layout_without_adj_tempo_is_no_data():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["", "rk", "team", "conf", "rec", "adj_o", "adj_o_rk",
                "adj_d", "adj_d_rk", "barthag", "proj_rec",
                "proj_conf_rec", "wab", "wab_rk", "cur_rk", "change",
                "date"])
    w.writerow([1, 1, "Duke", "ACC", "0-0", 110.0, 1, 90.0, 1, 0.95,
                "26-3", "15-1", 0, 294, 1, 0, "2022-11-06"])
    raw = buf.getvalue().encode("utf-8")
    # The 2022-11-06 drift file (the D-1 file for games on
    # 2022-11-07) has no adj_tempo: no totals input can be supplied,
    # so the date is NO_DATA — no tempo is substituted or imputed.
    assert runner.parse_torvik(raw, "2022-11-06", _RESOLVE) is None


# ------------------------------------------------- prior-snapshot probe

def _write_cache(cache_dir, stamp, records):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["team", "record", "date"])
    file_date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    for team, record in records:
        w.writerow([team, record, file_date])
    (cache_dir / f"ratings_archive_{stamp}.csv").write_bytes(
        buf.getvalue().encode("utf-8"))


def test_prior_snapshot_probe_passes_on_the_declared_values(tmp_path):
    _write_cache(tmp_path, "20141113", [("Duke", "0-0"),
                                        ("Kentucky", "0-0"),
                                        ("Wisconsin", "0-0")])
    _write_cache(tmp_path, "20230311", [("Purdue", "28-5")])
    passed, witnesses = runner.prior_snapshot_probe(tmp_path)
    assert passed is True
    assert len(witnesses) == 4


def test_prior_snapshot_probe_fails_on_a_contaminated_file(tmp_path):
    _write_cache(tmp_path, "20141113", [("Duke", "1-0"),  # same-day leak
                                        ("Kentucky", "0-0"),
                                        ("Wisconsin", "0-0")])
    _write_cache(tmp_path, "20230311", [("Purdue", "28-5")])
    passed, witnesses = runner.prior_snapshot_probe(tmp_path)
    assert passed is False
    assert witnesses[0]["observed"] == "1-0"


# ---------------------------------------------------- model arithmetic

def test_expected_points_formula_is_the_designs():
    # (adj_o + opp adj_d - league mean) / 100 * possessions
    assert runner.expected_points(110.0, 90.0, 100.0, 70.0) == 70.0


def test_candidate_points_use_the_tempo_blend():
    fx = {"tempo_home": 70.0, "tempo_away": 66.0,
          "adj_o_home": 110.0, "adj_d_away": 90.0,
          "adj_o_away": 104.0, "adj_d_home": 96.0,
          "league_mean_eff": 100.0}
    pts_home, pts_away = runner.candidate_points(fx)
    assert pts_home == (110.0 + 90.0 - 100.0) / 100.0 * 68.0
    assert pts_away == (104.0 + 96.0 - 100.0) / 100.0 * 68.0


def test_bootstrap_of_a_constant_difference_is_exact():
    diffs = {"2015-16": [-1.0, -1.0], "2016-17": [-1.0]}
    out = runner.season_block_bootstrap(diffs)
    assert out["mean_paired_diff"] == -1.0
    assert out["ci95_upper"] == -1.0  # every resample is identical
    assert out["seed"] == 20261028 and out["reps"] == 10000
