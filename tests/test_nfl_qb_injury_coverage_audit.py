import csv
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/audit_nfl_qb_injury_coverage.py")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    assert rows
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_roster_qb_without_injury_row_fails_closed(tmp_path):
    injuries = []
    rosters = []
    for season in range(2009, 2026):
        for week in range(1, 19):
            key = f"QB-{season}-{week}"
            rosters.append(
                {"season": season, "week": week, "position": "QB", "team": "T", "gsis_id": key}
            )
            if not (season == 2009 and week == 1):
                injuries.append(
                    {
                        "season": season,
                        "week": week,
                        "position": "QB",
                        "report_status": "Questionable",
                        "gsis_id": key,
                        "date_modified": f"{season}-09-01T00:00:00Z",
                    }
                )

    injury_path = tmp_path / "inj.csv"
    roster_path = tmp_path / "ros.csv"
    output_path = tmp_path / "out.json"
    _write_csv(injury_path, injuries)
    _write_csv(roster_path, rosters)

    process = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(injury_path),
            "--weekly-rosters",
            str(roster_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode != 0
    output = json.loads(output_path.read_text())
    assert output["status"] == "FAIL_CLOSED"
    assert output["roster_qb_keys_without_injury_row"] == 1
    assert output["unmatched_by_season_week"]["2009-01"] == 1
    assert output["missing_state_policy"] == "ROSTER_QB_WITHOUT_PIT_INJURY_ROW_IS_MISSING_NOT_AVAILABLE"
    assert output["development_validation_scoring_authority"] is False
