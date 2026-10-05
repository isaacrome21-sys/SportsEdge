import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "research_mlb_f5_nrfi_production_parity",
    ROOT / "scripts" / "research_mlb_f5_nrfi_production_parity.py",
)
P = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = P
assert SPEC.loader is not None
SPEC.loader.exec_module(P)


def test_candidate_is_fixed_m30_without_search_grid():
    assert P.PRIOR_STRENGTH == 30
    assert P.CAND_F5 == "candidate_m30"
    assert P.CAND_NRFI == "candidate_m30"
    assert P.PRODUCTION_LOOKBACK_DAYS == 240
    assert P.LEAGUE_LOOKBACK_DAYS == 370


def test_prior_team_matches_live_240_day_last_30_semantics():
    target = date(2026, 4, 1)
    rows = []
    for i in range(35):
        rows.append({"day": target - timedelta(days=35 - i), "id": i})
    rows.insert(0, {"day": target - timedelta(days=241), "id": -1})
    rows.append({"day": target, "id": 999})
    got = P.prior_team(rows, target)
    assert len(got) == 30
    assert got[0]["id"] == 5
    assert got[-1]["id"] == 34
    assert all(row["day"] < target for row in got)


def test_prior_halves_uses_370_days_and_excludes_target_day():
    target = date(2026, 10, 1)
    rows = [
        (target - timedelta(days=371), 1, 1),
        (target - timedelta(days=370), 2, 0),
        (target - timedelta(days=1), 3, 1),
        (target, 4, 0),
    ]
    got = P.prior_halves(rows, target)
    assert got == [
        (target - timedelta(days=370), 2, 0),
        (target - timedelta(days=1), 3, 1),
    ]


def test_summary_has_no_retuning_and_can_ship_both_fixed_candidates():
    old_min = P.MIN_TEST_GAMES
    old_reps = P.R.BOOT_REPS
    old_seed = P.R.BOOT_SEED
    try:
        P.MIN_TEST_GAMES = 1
        P.R.BOOT_REPS = 100
        P.R.BOOT_SEED = P.BOOT_SEED
        f5_rows = []
        nrfi_rows = []
        for day in range(1, 11):
            date_key = f"2026-07-{day:02d}"
            f5_rows.append({
                "date": date_key,
                P.BASE_F5: {"nll": 2.0, "state_brier": 0.25, "total45_brier": 0.24},
                P.CAND_F5: {"nll": 1.0, "state_brier": 0.24, "total45_brier": 0.23},
            })
            nrfi_rows.append({
                "date": date_key,
                "nrfi": 1,
                P.BASE_NRFI: {"p": 0.60, "logloss": 0.60, "brier": 0.20},
                P.CAND_NRFI: {"p": 0.70, "logloss": 0.40, "brier": 0.10},
            })
        out = P.summarize(f5_rows, nrfi_rows)
        assert out["candidate"] == {"prior_strength": 30, "retuned": False}
        assert out["f5"]["ships"] is True
        assert out["nrfi"]["ships"] is True
    finally:
        P.MIN_TEST_GAMES = old_min
        P.R.BOOT_REPS = old_reps
        P.R.BOOT_SEED = old_seed
