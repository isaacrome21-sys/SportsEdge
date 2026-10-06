import json
from pathlib import Path

import pytest

from scripts import run_mlb_pitcher_k_full_season_evaluation as R


def _row(season, i):
    return {
        "season": season,
        "target_date": f"{season}-06-01",
        "game_id": season * 100000 + i,
        "pitcher_id": str(5000 + i),
        "historical_reconstruction": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
    }


def _payload(n2025=500):
    rows = [_row(2023, i) for i in range(2)]
    rows += [_row(2024, i) for i in range(2)]
    rows += [_row(2025, i) for i in range(n2025)]
    return {
        "schema": R.ROWS_SCHEMA,
        "seasons": [2023, 2024, 2025],
        "row_count": len(rows),
        "season_receipts": [],
        "rows": rows,
        "historical_reconstruction": True,
        "backfill": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "authority": {
            "model_p": False, "truth_gate": False, "promotion": False,
            "staking": False, "official": False, "bettor_facing_release": False,
        },
    }


def test_load_rows_requires_full_seasons_minimum_test_and_zero_authority(tmp_path: Path):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    payload, digest = R.load_rows(path)
    assert payload["row_count"] == 504
    assert len(digest) == 64

    bad = _payload(499)
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(R.PitcherKFullSeasonEvalError, match="at least 500"):
        R.load_rows(path)

    bad = _payload()
    bad["forward_evidence_eligible"] = True
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(R.PitcherKFullSeasonEvalError, match="cannot be forward evidence"):
        R.load_rows(path)


def test_duplicate_rows_fail_closed(tmp_path: Path):
    payload = _payload()
    payload["rows"].append(dict(payload["rows"][0]))
    payload["row_count"] += 1
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(R.PitcherKFullSeasonEvalError, match="duplicate"):
        R.load_rows(path)


def test_run_requires_explicit_candidate_test_consumption(tmp_path: Path):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(R.PitcherKFullSeasonEvalError, match="consume-candidate-test"):
        R.run(path, out_dir=tmp_path / "out", consume_candidate_test=False)
