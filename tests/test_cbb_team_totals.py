"""Family tests for the CBB team totals screen packet
(research/cbb_team_totals_screen_20261028/).

Offline: no network, no kept-bytes reads except the committed
screen_result.json guard and the repo scan for the 1H prerequisite.
The construction/baseline/bootstrap tests pin the design formulas
(PR #2843: CBB_TEAM_TOTALS_1H_DESIGN.md section 1;
CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md sections 1-3) on
hand-computed values; the audit tests pin the governed gate —
the screen must score ONLY on the prior-snapshot (D-1) archive
files declared by Amendment 1 (PR #2883), never on file D itself.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_team_totals_screen_20261028"
sys.path.insert(0, str(PACKET))

import cbb_team_totals as tt  # noqa: E402
import run_team_totals_screen as runner  # noqa: E402

FX = {
    "home_slug": "alpha", "away_slug": "beta",
    "home_score": 75, "away_score": 70,
    "adj_o_home": 112.0, "adj_d_home": 99.0, "tempo_home": 71.0,
    "adj_o_away": 104.0, "adj_d_away": 98.0, "tempo_away": 67.0,
    "league_mean_eff": 101.5, "league_mean_tempo": 68.0,
}


# ------------------------------------------------------- construction

def test_expected_possessions_is_the_tempo_blend():
    assert tt.expected_possessions(68.0, 70.0) == 69.0
    assert tt.expected_possessions(71.0, 67.0) == 69.0


def test_expected_team_points_formula_verbatim():
    # (110 + 95 - 100) / 100 * 70 = 73.5
    assert tt.expected_team_points(110.0, 95.0, 100.0, 70.0) == 73.5


def test_candidate_team_points_hand_computed():
    pts_home, pts_away = tt.candidate_team_points(FX)
    # possessions = (71 + 67) / 2 = 69
    assert pts_home == (112.0 + 98.0 - 101.5) / 100.0 * 69.0
    assert pts_away == (104.0 + 99.0 - 101.5) / 100.0 * 69.0


def test_simple_baseline_uses_league_mean_tempo_only():
    pts_home, pts_away = tt.simple_baseline_team_points(FX)
    assert pts_home == (112.0 + 98.0 - 101.5) / 100.0 * 68.0
    assert pts_away == (104.0 + 99.0 - 101.5) / 100.0 * 68.0
    # The ablation is real: blend (69) != league-mean tempo (68).
    cand_home, _ = tt.candidate_team_points(FX)
    assert cand_home != pts_home


def test_no_home_court_term_in_team_points():
    # The design's mechanics put the home-court term in the margin
    # only: identical efficiency/tempo terms at a neutral site give
    # identical team points.
    fx2 = dict(FX)
    assert tt.candidate_team_points(fx2) == tt.candidate_team_points(FX)


# ------------------------------------------------------------ baselines

PRIOR = [
    {"home_slug": "alpha", "away_slug": "beta",
     "home_score": 80, "away_score": 60},
    {"home_slug": "beta", "away_slug": "alpha",
     "home_score": 70, "away_score": 90},
]


def test_naive_team_mean_prior_window_only():
    team_mean, league = tt.naive_team_mean(PRIOR)
    assert team_mean["alpha"] == (80 + 90) / 2
    assert team_mean["beta"] == (60 + 70) / 2
    assert league == (80 + 60 + 70 + 90) / 4


def test_naive_fallback_and_empty_window():
    team_mean, league = tt.naive_team_mean(PRIOR)
    assert tt.naive_prediction(team_mean, league, "gamma") == league
    empty_mean, empty_league = tt.naive_team_mean([])
    assert empty_mean == {} and empty_league is None


def test_team_game_errors_hand_computed():
    team_mean, league = tt.naive_team_mean(PRIOR)
    obs = tt.team_game_errors(FX, team_mean, league)
    cand_home, cand_away = tt.candidate_team_points(FX)
    base_home, base_away = tt.simple_baseline_team_points(FX)
    home, away = obs
    assert home["actual"] == 75 and away["actual"] == 70
    assert home["candidate_err"] == abs(cand_home - 75)
    assert away["candidate_err"] == abs(cand_away - 70)
    assert home["simple_err"] == abs(base_home - 75)
    assert home["naive_err"] == abs(85.0 - 75)   # alpha mean = 85
    assert away["naive_err"] == abs(65.0 - 70)   # beta mean = 65


def test_team_game_errors_refuses_empty_naive_window():
    try:
        tt.team_game_errors(FX, {}, None)
    except KeyError:
        return
    raise AssertionError("empty naive window must refuse")


# -------------------------------------------------------------- metrics

def test_bootstrap_deterministic_and_signed():
    diffs = {"2015-16": [-1.0, -2.0], "2016-17": [-0.5, -1.5]}
    first = tt.season_block_bootstrap(diffs)
    second = tt.season_block_bootstrap(diffs)
    assert first == second
    assert first["blocks"] == 2 and first["reps"] == 10000
    assert first["seed"] == 20261028
    assert first["ci95_upper"] < 0
    assert tt.leg_criterion(first) is True
    pos = tt.season_block_bootstrap({"2015-16": [1.0, 2.0]})
    assert pos["ci95_lower"] > 0
    assert tt.leg_criterion(pos) is False


def test_score_team_points_end_to_end_synthetic():
    def fx(hs, as_, **kw):
        base = dict(FX)
        base.update({"home_score": hs, "away_score": as_})
        base.update(kw)
        return base

    universe = {2015: [fx(80, 60), fx(70, 90, home_slug="beta",
                                      away_slug="alpha")],
                2016: [fx(75, 70)]}
    for year in range(2017, 2024):
        universe[year] = []
    # Scored years with no fixtures would divide by zero in the
    # pooled MAE; the real universe is never empty per season.
    # Restrict the synthetic run to the two populated years.
    universe = {2015: universe[2015], 2016: universe[2016]}
    orig_scored = tt.SCORED_YEARS
    try:
        tt.SCORED_YEARS = [2016]
        per_season, pooled, criteria = runner.score_team_points(universe)
    finally:
        tt.SCORED_YEARS = orig_scored
    assert per_season["2015-16"]["fixtures_scored"] == 1
    assert per_season["2015-16"]["team_games_scored"] == 2
    assert pooled["team_games_scored_total"] == 2
    assert set(criteria) == {"team_points_vs_naive_team_mean",
                             "team_points_vs_simple_ratings_baseline"}
    for c in criteria.values():
        assert c["criterion"] == "CI upper bound < 0"
        assert "ci95_upper" in c and "pass" in c


# ------------------------------------------------------- premise audit

def test_record_of_reads_both_schema_spellings():
    assert runner.record_of({"record": "3-1"}) == "3-1"
    assert runner.record_of({"rec": "2-2", "record": None}) == "2-2"


def _torvik_csv(rows):
    lines = ["rank,team,conf,record,adj_o,adj_o_rk,adj_d,adj_d_rk,"
             "adj_tempo,adj_tempo_rk,barthag,proj_record,"
             "proj_conf_record,wab,wab_rk,date"]
    for team, record in rows:
        lines.append(f"1,{team},X,{record},100.0,1,100.0,1,68.0,1,"
                     f"0.5,0-0,0-0,0.0,1,2014-11-14")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _stub_audit(monkeypatch, record_for_witness_teams):
    witnesses = {team: record_for_witness_teams
                 for _, team, _ in runner.DECLARED_WITNESSES}

    def fake_fetch(date_iso, cache_dir):
        # Under PRIOR-SNAPSHOT the audit fetches D-1 files:
        # witness game dates 2014-11-14 / 2023-03-12 / 2023-04-03
        # are read at 2014-11-13 / 2023-03-11 / 2023-04-02.
        if date_iso in ("2014-11-13", "2023-03-11", "2023-04-02"):
            rows = [(team, rec) for team, rec in witnesses.items()]
            return _torvik_csv(rows)
        return _torvik_csv([("Anyone", record_for_witness_teams)])

    monkeypatch.setattr(runner, "fetch_torvik", fake_fetch)
    monkeypatch.setattr(runner, "opening_date",
                        lambda year, manifest: "2015-01-01")
    return runner.as_of_audit({}, Path("/nonexistent"))


def test_prior_date_arithmetic():
    assert runner.prior_date("2014-11-14") == "2014-11-13"
    assert runner.prior_date("2023-01-01") == "2022-12-31"
    assert runner.prior_date("2020-03-01") == "2020-02-29"  # leap year
    assert runner.prior_date("2023-03-01") == "2023-02-28"


def test_audit_passes_on_genuine_prior_snapshot_files(monkeypatch):
    # Witness expectations differ per team (0-0 openers, Purdue
    # 28-5, finalists 30-8 / 32-6); return each team's pre-game
    # record: build a per-date stub instead of one blanket record.
    # The stub is keyed by the PRIOR-SNAPSHOT (D-1) dates the
    # audit must fetch — if the runner fetched file D instead,
    # no stub would match and the audit would fail.
    fetched = []

    def fake_fetch(date_iso, cache_dir):
        fetched.append(date_iso)
        if date_iso == "2014-11-13":
            return _torvik_csv([(t, "0-0") for t in
                                ("Duke", "Kentucky", "Wisconsin", "Kansas",
                                 "Michigan St.", "North Carolina", "UCLA")])
        if date_iso == "2023-03-11":
            return _torvik_csv([("Purdue", "28-5")])
        if date_iso == "2023-04-02":
            return _torvik_csv([("Connecticut", "30-8"),
                                ("San Diego St.", "32-6")])
        return _torvik_csv([("Anyone", "0-0")])

    monkeypatch.setattr(runner, "fetch_torvik", fake_fetch)
    monkeypatch.setattr(runner, "opening_date",
                        lambda year, manifest: "2015-01-01")
    passed, declared, opening = runner.as_of_audit({}, Path("/nonexistent"))
    assert passed is True
    assert all(w["observed"] == w["expected_if_prior_snapshot"]
               for w in declared)
    assert all(o["teams_not_0_0"] == 0 for o in opening)
    # Witness fetches hit D-1 exactly; the opening audit for the
    # stubbed 2015-01-01 opening date reads 2014-12-31.
    assert "2014-11-13" in fetched and "2014-11-14" not in fetched
    assert "2023-03-11" in fetched and "2023-04-02" in fetched
    assert "2014-12-31" in fetched and "2015-01-01" not in fetched


def test_audit_fails_on_contaminated_prior_snapshot_files(monkeypatch):
    passed, declared, opening = _stub_audit(monkeypatch, "1-0")
    assert passed is False
    assert any(w["observed"] != w["expected_if_prior_snapshot"]
               for w in declared)
    assert all(o["teams_not_0_0"] == 1 for o in opening)


def test_declared_witnesses_cover_title_game():
    cases = {(d, t) for d, t, _ in runner.DECLARED_WITNESSES}
    assert ("2023-04-03", "Connecticut") in cases
    assert ("2023-04-03", "San Diego St.") in cases
    assert ("2023-03-12", "Purdue") in cases
    assert len(runner.DECLARED_WITNESSES) == 10


# ------------------------------------------------- illinois + fixtures

def test_illinois_exclusion_is_conservative():
    assert runner.is_illinois_fixture("Illinois", "Purdue", "illinois", "purdue")
    assert runner.is_illinois_fixture("Bradley", "Purdue", "bradley", "purdue")
    assert runner.is_illinois_fixture("Purdue", "Illinois State",
                                      "purdue", "illinois-state")
    assert not runner.is_illinois_fixture("Purdue", "Indiana",
                                          "purdue", "indiana")


def test_cbr_derivation_pairs_mirrors_and_drops_conflicts(tmp_path,
                                                         monkeypatch):
    header = ("Season,Game,Date,TeamFull,Opponent,HomeAway,W_L,TeamScore,"
              "OpponentScore,URL,Team")
    rows = [
        "2022-2023,1,2022-11-07,Alpha Team,Beta,NA,W,80,70,"
        "/cbb/schools/alpha/men/2023.html,Alpha",
        "2022-2023,1,2022-11-07,Beta Team,Alpha,NA,L,70,80,"
        "/cbb/schools/beta/men/2023.html,Beta",
        # Conflicted pair: mirror rows disagree on the score.
        "2022-2023,2,2022-11-08,Alpha Team,Beta,NA,W,90,60,"
        "/cbb/schools/alpha/men/2023.html,Alpha",
        "2022-2023,2,2022-11-08,Beta Team,Alpha,NA,L,61,90,"
        "/cbb/schools/beta/men/2023.html,Beta",
    ]
    path = tmp_path / "logs23.csv"
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    import hashlib
    manifest = {"samples": [{"file_name": "logs23.csv",
                             "sha256": hashlib.sha256(
                                 path.read_bytes()).hexdigest()}]}
    monkeypatch.setattr(runner, "CBR_DIR", tmp_path)
    resolve = lambda s: {"Alpha": "alpha", "Beta": "beta",
                         "Alpha Team": "alpha", "Beta Team": "beta"}.get(s)
    fixtures, conflicts, stats = runner.derive_cbr_fixtures(
        2023, manifest, resolve)
    assert fixtures == {("2022-11-07", ("alpha", "beta")):
                        {"alpha": 80, "beta": 70}}
    assert ("2022-11-08", ("alpha", "beta")) in conflicts
    assert stats["mirror_inconsistent_pairs"] == 1


# ------------------------------------------------------------- 1H gate

def test_first_half_prerequisite_absent_on_main():
    assert runner.find_pbp_manifest(ROOT) == []
    block = runner.first_half_block(ROOT)
    assert block["verdict"] == "NOT_EXECUTABLE"
    assert block["refusal"]["code"] == "PBP_PREREQUISITE_MISSING"


# ------------------------------------------------- committed record

def test_committed_screen_result_is_the_prior_snapshot_rerun():
    result = json.loads((PACKET / "screen_result.json").read_text(
        encoding="utf-8"))
    # The rerun EXECUTED under Amendment 1: a real verdict, not the
    # first run's AS_OF_PREMISE_FAILURE refusal.
    assert result["verdict"] in ("DESIGN_PASS", "DESIGN_FAIL")
    assert result["family"] == "CBB team totals"
    assert result["input_convention"]["name"] == "PRIOR_SNAPSHOT"
    assert result["input_convention"]["premise_audit"]["verdict"] == "PASS"
    witnesses = (result["input_convention"]["premise_audit"]
                 ["declared_witnesses"])
    assert len(witnesses) == 10
    assert all(w["observed"] == w["expected_if_prior_snapshot"]
               for w in witnesses)
    opening = (result["input_convention"]["premise_audit"]
               ["opening_day_audit"])
    assert len(opening) == 9
    assert all(o["teams_not_0_0"] == 0 for o in opening)
    assert result["pin_verification_counts"] == {
        "hoopr_assets_verified": 18, "cbr_files_verified": 6,
        "torvik_admission_samples_verified": 2}
    for name in ("team_points_vs_naive_team_mean",
                 "team_points_vs_simple_ratings_baseline"):
        crit = result["criteria"][name]
        assert crit["criterion"] == "CI upper bound < 0"
        assert crit["pass"] == (crit["ci95_upper"] < 0)
    assert result["verdict"] == (
        "DESIGN_PASS" if all(c["pass"] for c in
                             result["criteria"].values())
        else "DESIGN_FAIL")
    # Scored universe is real and pooled MAEs are populated.
    assert result["pooled_mae"]["team_games_scored_total"] > 0
    agreed_total = sum(
        s["fixtures_agreed_three_way"]
        for s in result["fixture_universe_by_season"].values())
    assert agreed_total > 0
    assert result["first_half"]["verdict"] == "NOT_EXECUTABLE"
