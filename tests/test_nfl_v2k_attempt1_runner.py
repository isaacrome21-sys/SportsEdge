from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sportsedge.sports.nfl import v2k_attempt1_validation as v
from sportsedge.sports.nfl.v2k_drive_source import build_drive_rows_from_pbp

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_nfl_v2k_attempt1.py"
ROOT_SEED = 15264549103493747052


def _p(seq, drive, qtr, secs, ptype, pos, de, result, yl, ph, pa, **extra):
    """One nflverse-shaped play. Scores are cumulative (home, away) after the play."""
    row = {
        "_seq": seq, "play_id": str(1000 - seq), "game_id": "2018_01_LA_OAK", "game_date": "2018-09-10",
        "season_type": "REG", "home_team": "LV", "away_team": "LA",
        "fixed_drive": str(drive), "qtr": str(qtr), "quarter_seconds_remaining": str(secs),
        "play_type": ptype, "posteam": pos, "defteam": de, "fixed_drive_result": result,
        "yardline_100": str(yl), "total_home_score": str(ph), "total_away_score": str(pa),
        "posteam_score": "", "defteam_score": "", "extra_point_result": "", "two_point_conv_result": "",
        "two_point_attempt": "0",
    }
    row.update({k: str(v_) for k, v_ in extra.items()})
    return row


IDENTITY = {"game_id": "2018_01_LA_OAK", "season": 2018, "week": 1,
            "home_team": "OAK", "away_team": "LA", "home_score": 14, "away_score": 7}


def _game():
    # play_id deliberately runs backwards: ordering must come from file order.
    return [
        _p(0, 1, 1, 900, "kickoff", "LA", "LV", "Touchdown", 35, 0, 0, posteam_score=0, defteam_score=0),
        _p(1, 1, 1, 895, "run", "LA", "LV", "Touchdown", 75, 0, 0, posteam_score=0, defteam_score=0),
        _p(2, 1, 1, 850, "pass", "LA", "LV", "Touchdown", 20, 0, 6, posteam_score=0, defteam_score=0),
        _p(3, 1, 1, 850, "extra_point", "LA", "LV", "Touchdown", 15, 0, 7, extra_point_result="good"),
        _p(4, 1, 1, 850, "", "LA", "LV", "Touchdown", "", 0, 7),  # admin row
        _p(5, 2, 1, 845, "no_play", "LV", "LA", "", 35, 0, 7),  # phantom re-kick drive
        _p(6, 3, 1, 845, "kickoff", "LV", "LA", "Touchdown", 35, 0, 7, posteam_score=0, defteam_score=7),
        _p(7, 3, 1, 840, "run", "LV", "LA", "Touchdown", 70, 0, 7, posteam_score=0, defteam_score=7),
        _p(8, 3, 2, 30, "pass", "LV", "LA", "Touchdown", 5, 6, 7, posteam_score=0, defteam_score=7),
        _p(9, 3, 2, 30, "pass", "LV", "LA", "Touchdown", 2, 6, 7, two_point_attempt=1, two_point_conv_result="failure"),
        _p(10, 4, 2, 25, "kickoff", "LA", "LV", "End of half", 35, 6, 7, posteam_score=7, defteam_score=6),
        _p(11, 4, 2, 20, "qb_kneel", "LA", "LV", "End of half", 75, 6, 7, posteam_score=7, defteam_score=6),
        _p(12, 5, 3, 900, "kickoff", "LV", "LA", "Field goal", 35, 6, 7, posteam_score=6, defteam_score=7),
        _p(13, 5, 3, 880, "pass", "LV", "LA", "Field goal", 60, 6, 7, posteam_score=6, defteam_score=7),
        _p(14, 5, 4, 100, "field_goal", "LV", "LA", "Field goal", 30, 9, 7, posteam_score=6, defteam_score=7),
        _p(15, 6, 4, 95, "kickoff", "LA", "LV", "Punt", 35, 9, 7, posteam_score=7, defteam_score=9),
        _p(16, 6, 4, 90, "punt", "LA", "LV", "Punt", 80, 9, 7, posteam_score=7, defteam_score=9),
        _p(17, 7, 4, 60, "pass", "LV", "LA", "Touchdown", 40, 15, 7, posteam_score=9, defteam_score=7),
        _p(18, 7, 4, 60, "extra_point", "LV", "LA", "Touchdown", 15, 16, 7, extra_point_result="good"),
        _p(19, 8, 4, 55, "kickoff", "LA", "LV", "End of half", 35, 16, 7, posteam_score=7, defteam_score=16),
        _p(20, 8, 4, 40, "qb_kneel", "LA", "LV", "End of half", 75, 14, 7, posteam_score=7, defteam_score=16),
    ]


def test_pbp_drive_records_map_teams_order_conversions_and_terminations():
    recs = v.pbp_game_drive_records(_game(), IDENTITY)
    assert [r["drive_id"] for r in recs] == [1, 3, 4, 5, 6, 7, 8]  # phantom drive 2 skipped
    first = recs[0]
    assert (first["offense"], first["defense"]) == ("LA", "OAK")  # LV -> schedule OAK
    assert first["start_yardline_100"] == 75.0  # first scrimmage snap, not the kickoff
    assert first["conversion_points"] == 1 and first["offense_score_after"] == 7
    assert recs[1]["conversion_points"] == 0  # failed two-point try
    assert recs[1]["period"] == 1 and recs[1]["clock_seconds_remaining_period"] == 845
    assert recs[2]["drive_result"] == "end_of_half"
    assert recs[-1]["drive_result"] == "end_of_game"
    rows = build_drive_rows_from_pbp(recs, source_manifest_sha256="m", source_code_sha="c")
    assert [r.outcome for r in rows] == ["TD", "TD", "PUNT_OTHER", "FG", "PUNT_OTHER", "TD", "PUNT_OTHER"]
    assert rows[2].termination_reason == "END_OF_HALF" and rows[-1].termination_reason == "END_OF_GAME"


def test_regulation_expiring_tied_is_not_end_of_game():
    plays = _game()
    # Insert an overtime drive after the Q4 "End of half" drive.
    plays.append(_p(21, 9, 5, 600, "kickoff", "LV", "LA", "Field goal", 35, 16, 7, posteam_score=16, defteam_score=7))
    plays.append(_p(22, 9, 5, 500, "field_goal", "LV", "LA", "Field goal", 20, 19, 7, posteam_score=16, defteam_score=7))
    recs = v.pbp_game_drive_records(plays, IDENTITY)
    assert recs[-2]["drive_result"] == "punt" and recs[-1]["drive_result"] == "field_goal"


def test_unknown_drive_result_and_foreign_team_fail_closed():
    plays = _game()
    plays[1]["fixed_drive_result"] = "Mystery"
    for p in plays:
        if p["fixed_drive"] == "1":
            p["fixed_drive_result"] = "Mystery"
    with pytest.raises(ValueError, match="V2K_DRIVE_RESULT_UNMAPPED"):
        v.pbp_game_drive_records(plays, IDENTITY)
    plays = _game()
    plays[1]["posteam"] = "KC"
    with pytest.raises(ValueError, match="V2K_PBP_TEAM_NOT_IN_GAME"):
        v.pbp_game_drive_records(plays, IDENTITY)


def _schedule():
    sched = {}
    for season in range(2021, 2026):
        for i, (h, a, hs, as_) in enumerate((("KC", "BUF", 27, 20), ("NE", "NYJ", 13, 17))):
            gid = f"{season}_01_{a}_{h}_{i}"
            sched[gid] = {"game_id": gid, "season": season, "week": 1, "home_team": h, "away_team": a,
                          "home_score": hs, "away_score": as_,
                          "_market": {"spread_line": 3.0, "total_line": 44.5, "home_spread_odds": "-110",
                                      "away_spread_odds": "-110", "over_odds": "-110", "under_odds": "-110"}}
    return sched


def _shards(sched, contract, *, drop=None):
    folds = {f["test_season"]: f["fold_id"] for f in contract["attempt1_issue_binding"]["fold_plan"]["folds"]}
    out = []
    for season, fold_id in folds.items():
        games = []
        for g in sched.values():
            if g["season"] != season or g["game_id"] == drop:
                continue
            games.append({"game_id": g["game_id"], "season": season, "week": 1, "home_team": g["home_team"],
                          "away_team": g["away_team"], "paths": 4,
                          "margin_hist": {"-3": 1, "3": 2, "7": 1}, "total_hist": {"40": 2, "50": 2}})
        out.append({"schema": v.SHARD_SCHEMA, "root_seed": ROOT_SEED, "fold_id": fold_id, "shard_index": 0,
                    "shard_count": 1, "paths_per_game": 4, "games": games})
    return out


def test_evaluate_reads_market_only_from_schedule_and_produces_gates():
    contract = json.loads(v.CONTRACT_PATH.read_text())
    sched = _schedule()
    assert all("_market" not in g for g in v.schedule_identity(sched).values())
    result = v.evaluate(_shards(sched, contract), sched, contract)
    assert result["verdict"] in ("ATTEMPT1_PASS", "ATTEMPT1_FAIL")
    assert result["evaluated_game_count"] == len(sched)
    s = result["structural_gate"]
    assert s["candidate_signed_key_probability"] == {"-7": 0.0, "-3": 0.25, "3": 0.5, "7": 0.25}
    row = result["game_rows"][0]
    assert row["m2_home_cover_prob"] == pytest.approx(0.5)  # margin 3 pushes; 1 win of 2 non-push
    assert row["m2_over_prob"] == pytest.approx(0.5)
    assert row["m1_home_cover_prob"] == pytest.approx(0.5)
    assert result["sportsbook_prices_consumed_in_fit"] is False
    assert all(a is False for a in result["authority"].values())


def test_evaluate_fails_closed_on_missing_duplicate_or_drifted_games():
    contract = json.loads(v.CONTRACT_PATH.read_text())
    sched = _schedule()
    with pytest.raises(SystemExit, match="V2K_EVALUATED_GAME_SET_MISMATCH"):
        v.evaluate(_shards(sched, contract, drop=next(iter(sched))), sched, contract)
    shards = _shards(sched, contract)
    shards[1]["games"].append(dict(shards[0]["games"][0]))
    with pytest.raises(SystemExit, match="V2K_DUPLICATE_GAME"):
        v.evaluate(shards, sched, contract)
    shards = _shards(sched, contract)
    shards[0]["games"][0]["home_team"] = "XXX"
    with pytest.raises(SystemExit, match="V2K_HOME_AWAY_DRIFT"):
        v.evaluate(shards, sched, contract)
    shards = _shards(sched, contract)
    shards[0]["shard_count"] = 2
    with pytest.raises(SystemExit, match="V2K_SHARDS_INCOMPLETE"):
        v.evaluate(shards, sched, contract)


def test_preflight_enforces_frozen_identity_and_path_rules():
    contract = v.preflight(paths=50000, smoke=False)  # frozen blobs + unconsumed ledger
    assert contract["attempt1_issue_binding"]["simulation_count_paths_per_game"] == 50000
    with pytest.raises(SystemExit, match="V2K_PATH_COUNT_NOT_FROZEN"):
        v.preflight(paths=20000, smoke=False)
    with pytest.raises(SystemExit, match="V2K_SMOKE_MUST_STAY_BELOW_FLOOR"):
        v.preflight(paths=10000, smoke=True)
    v.preflight(paths=100, smoke=True)


def test_runner_reads_fold_plan_from_contract_not_hardcoded():
    text = SCRIPT.read_text()
    assert "FOLDS=" not in text.replace(" ", "") and "range(2018" not in text
    folds = json.loads(v.CONTRACT_PATH.read_text())["attempt1_issue_binding"]["fold_plan"]["folds"]
    assert [(f["fold_id"], f["test_season"]) for f in folds] == [("F1", 2021), ("F2", 2022), ("F3", 2023), ("F4", 2024), ("F5", 2025)]
    out = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert out.returncode == 0 and "simulate" in out.stdout and "evaluate" in out.stdout


def test_simulation_histograms_are_shard_independent():
    from sportsedge.sports.nfl.v2k_drive_core import DriveRow, fit_hierarchical_strength
    rows = []
    for g in range(4):
        for i, (o, d, out) in enumerate((("A", "B", "TD"), ("B", "A", "FG"), ("A", "B", "PUNT"), ("B", "A", "TD"))):
            rows.append(DriveRow(game_id=f"g{g}", season=2018, week=1, kickoff_utc="t", drive_index=i, offense=o,
                                 defense=d, start_yardline_100=70.0, outcome="PUNT_OTHER" if out == "PUNT" else out,
                                 offense_score_before=0, defense_score_before=0, offense_score_after=0,
                                 defense_score_after=0, period=1 + i, clock_seconds_remaining_period=800,
                                 conversion_points=1 if out == "TD" else 0, source_manifest_sha256="m", source_code_sha="c"))
    model = fit_hierarchical_strength(rows)
    game = {"game_id": "2021_01_B_A", "season": 2021, "week": 1, "home_team": "A", "away_team": "B"}
    one = v.simulate_game_histograms(model, game, root_seed=ROOT_SEED, paths=50)
    two = v.simulate_game_histograms(model, game, root_seed=ROOT_SEED, paths=50)
    assert one == two and sum(one["margin_hist"].values()) == 50
